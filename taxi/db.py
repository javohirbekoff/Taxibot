"""Short SQLite transactions run off the event loop; no Telegram calls inside them."""
import asyncio
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


class UserError(Exception):
    pass


def one(c, sql, args=()):
    row = c.execute(sql, args).fetchone()
    return dict(row) if row else None


def enqueue(c, key, kind, chat, **payload):
    c.execute("INSERT OR IGNORE INTO outbox(dedup_key,kind,chat_id,payload,created_at) VALUES(?,?,?,?,?)",
              (key, kind, chat, json.dumps(payload, ensure_ascii=False), int(time.time())))


def driver_text(d):
    return (f"ID: {d['driver_id'] or 'Kutilmoqda'}\nIsm: {d['full_name']}\n"
            f"Mashina: {d['car_model']}\n"
            f"Davlat raqami: {d['car_number']}\nTelefon: {d['phone']}")


DRIVER_SQL = "SELECT d.*,u.full_name,u.phone FROM drivers d JOIN users u USING(telegram_id)"


class Database:
    def __init__(self, path, admins=(), driver_channel=-1, orders_channel=-2, commission=500):
        self.path = str(path)
        self.admins = admins
        self.driver_channel = driver_channel
        self.orders_channel = orders_channel
        self.commission = commission

    async def run(self, fn, write=True):
        def execute():
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            try:
                c.execute("PRAGMA foreign_keys=ON")
                c.execute("PRAGMA busy_timeout=30000")
                c.execute("PRAGMA synchronous=FULL")
                if write:
                    c.execute("BEGIN IMMEDIATE")
                result = fn(c)
                if write:
                    c.commit()
                return result
            except BaseException:
                if c.in_transaction:
                    c.rollback()
                raise
            finally:
                c.close()
        return await asyncio.to_thread(execute)

    async def init(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
        def init(c):
            version = c.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise RuntimeError(f'Unsupported schema version: {version}')
            if version in (1, 2):
                backup = sqlite3.connect(self.path + f'.v{version}-backup')
                try:
                    c.backup(backup)
                finally:
                    backup.close()
            c.executescript(schema)
            c.execute('BEGIN IMMEDIATE')
            c.execute('PRAGMA defer_foreign_keys=ON')
            ledger_sql = c.execute("SELECT sql FROM sqlite_master WHERE name='ledger'").fetchone()[0]
            if "'debit'" not in ledger_sql:
                c.execute("CREATE TABLE ledger_v3 (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                          "driver_id TEXT NOT NULL REFERENCES drivers(driver_id), amount INTEGER NOT NULL, "
                          "kind TEXT NOT NULL CHECK(kind IN ('topup','commission','debit')), "
                          "idempotency_key TEXT NOT NULL UNIQUE, actor INTEGER NOT NULL, created_at INTEGER NOT NULL)")
                c.execute('INSERT INTO ledger_v3 SELECT * FROM ledger')
                c.execute('DROP TABLE ledger')
                c.execute('ALTER TABLE ledger_v3 RENAME TO ledger')
            if version < 3:
                c.execute("DELETE FROM sessions WHERE state LIKE 'Registration:%'")
            additions = {'routes': {'fare': 'INTEGER NOT NULL DEFAULT 0', 'description': "TEXT NOT NULL DEFAULT ''"},
                         'orders': {'fare': 'INTEGER NOT NULL DEFAULT 0', 'route_description': "TEXT NOT NULL DEFAULT ''",
                                    'contact_phone': "TEXT NOT NULL DEFAULT ''", 'note': "TEXT NOT NULL DEFAULT ''"}}
            for table, columns in additions.items():
                known = {r[1] for r in c.execute(f'PRAGMA table_info({table})')}
                for name, definition in columns.items():
                    if name not in known:
                        c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
            if version < 2:
                for d in c.execute('SELECT telegram_id,driver_id FROM drivers').fetchall():
                    old, new = d['driver_id'], str(d['telegram_id'])
                    if old and old != new:
                        for table in ('orders', 'ledger'):
                            c.execute(f'UPDATE {table} SET driver_id=? WHERE driver_id=?', (new, old))
                        c.execute('UPDATE campaigns SET target=? WHERE target=?', (new, old))
                    c.execute('UPDATE drivers SET driver_id=? WHERE telegram_id=?', (new, d['telegram_id']))
                c.execute("UPDATE orders SET contact_phone=COALESCE((SELECT phone FROM users WHERE telegram_id=passenger_id),'') WHERE contact_phone=''")
                c.execute('DELETE FROM sessions')
                # Pending financial operations must not retain old display IDs.
                for job in c.execute("SELECT id,payload FROM outbox WHERE status IN ('pending','sending')").fetchall():
                    payload = job['payload']
                    for d in c.execute('SELECT id,telegram_id FROM drivers').fetchall():
                        payload = re.sub(r'DRV-' + str(1000+d['id']) + r'(?![0-9])', str(d['telegram_id']), payload)
                    c.execute('UPDATE outbox SET payload=? WHERE id=?', (payload, job['id']))
            c.execute("INSERT OR IGNORE INTO settings VALUES('start_text','🚖 Taxi & Post xizmatiga xush kelibsiz! Kerakli bo‘limni tanlang.')")
            c.execute("INSERT OR IGNORE INTO settings VALUES('admin_contact',?)", (f'tg://user?id={self.admins[0]}' if self.admins else '',))
            c.execute("INSERT OR IGNORE INTO settings VALUES('commission',?)", (str(self.commission),))
            # A process-wide file lock is held by bot.py before this recovery.
            c.execute("UPDATE outbox SET status='pending' WHERE status='sending'")
            c.execute('PRAGMA user_version=3')
            c.commit()
        await self.run(init, write=False)

    async def fetch(self, sql, args=()):
        return await self.run(lambda c: [dict(r) for r in c.execute(sql, args)], write=False)

    async def user(self, uid):
        rows = await self.fetch('SELECT * FROM users WHERE telegram_id=?', (uid,))
        return rows[0] if rows else None

    async def driver(self, uid):
        rows = await self.fetch(DRIVER_SQL + ' WHERE telegram_id=?', (uid,))
        return rows[0] if rows else None

    async def visit(self, uid):
        await self.run(lambda c: c.execute('INSERT OR IGNORE INTO visitors VALUES(?,?)', (uid, int(time.time()))).rowcount)

    async def register(self, uid, data, role):
        def save(c):
            existing = one(c, 'SELECT * FROM drivers WHERE telegram_id=?', (uid,))
            if existing and existing['status'] in ('pending', 'approved'):
                raise UserError("Haydovchi arizangiz mavjud. /profile ni bosing.")
            c.execute('INSERT INTO users VALUES(?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET '
                      'full_name=excluded.full_name,phone=excluded.phone,role=excluded.role',
                      (uid, data['name'], data['phone'], role, int(time.time())))
            if role == 'driver':
                c.execute('INSERT INTO drivers(telegram_id,birth_year,car_model,car_number,photo_file_id) '
                          'VALUES(?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET '
                          "birth_year=excluded.birth_year,car_model=excluded.car_model,car_number=excluded.car_number,"
                          "photo_file_id=excluded.photo_file_id,status='pending',revision=drivers.revision+1",
                          (uid, data.get('year', 0), data['car'], data['plate'], data['photo']))
                d = one(c, DRIVER_SQL + ' WHERE telegram_id=?', (uid,))
                c.execute('UPDATE drivers SET driver_id=? WHERE telegram_id=?', (str(uid), uid))
                d['driver_id'] = str(uid)
                for admin in self.admins:
                    enqueue(c, f"moderate:{d['id']}:{d['revision']}:{admin}", 'photo', admin,
                            photo=d['photo_file_id'], text='Yangi haydovchi arizasi\n' + driver_text(d),
                            buttons=[[('✅ Tasdiqlash', f"mod:yes:{d['id']}:{d['revision']}"),
                                      ('❌ Rad etish', f"mod:no:{d['id']}:{d['revision']}")]])
        await self.run(save)

    async def moderate(self, admin, did, revision, approve):
        if admin not in self.admins:
            raise UserError('Ruxsat yo‘q.')
        def change(c):
            d = one(c, DRIVER_SQL + ' WHERE d.id=?', (did,))
            if not d or d['status'] != 'pending' or d['revision'] != revision:
                raise UserError('Ariza allaqachon ko‘rib chiqilgan yoki yangilangan.')
            driver_id = str(d['telegram_id'])
            c.execute('UPDATE drivers SET status=?,driver_id=? WHERE id=?',
                      ('approved' if approve else 'rejected', driver_id, did))
            d['driver_id'] = driver_id
            key = f'moderated:{did}:{revision}'
            if approve:
                enqueue(c, key + ':user', 'send', d['telegram_id'], text=f'Tasdiqlandingiz! Telegram ID: {driver_id}', driver_menu=True)
                enqueue(c, key + ':channel', 'photo', self.driver_channel,
                        photo=d['photo_file_id'], text=driver_text(d))
                enqueue(c, key + ':invite', 'invite', d['telegram_id'])
            else:
                enqueue(c, key, 'send', d['telegram_id'], text='Arizangiz rad etildi. /start orqali qayta topshirishingiz mumkin.')
            return driver_id
        return await self.run(change)

    async def topup(self, admin, driver_id, amount, key):
        if admin not in self.admins or not 0 < amount <= 1_000_000_000:
            raise UserError('Summa yoki ruxsat noto‘g‘ri.')
        def change(c):
            old = one(c, 'SELECT * FROM ledger WHERE idempotency_key=?', (key,))
            if old:
                return False
            d = one(c, 'SELECT * FROM drivers WHERE driver_id=? AND status=\'approved\'', (driver_id,))
            if not d:
                raise UserError('Tasdiqlangan haydovchi topilmadi.')
            if d['balance'] + amount > 9_000_000_000_000_000:
                raise UserError('Balans chegarasidan oshdi.')
            c.execute('UPDATE drivers SET balance=balance+? WHERE driver_id=?', (amount, driver_id))
            c.execute('INSERT INTO ledger(driver_id,amount,kind,idempotency_key,actor,created_at) VALUES(?,?,?,?,?,?)',
                      (driver_id, amount, 'topup', key, admin, int(time.time())))
            enqueue(c, key, 'send', d['telegram_id'], text=f"Balans +{amount:,} so‘m. Jami: {d['balance']+amount:,} so‘m.")
            return True
        return await self.run(change)

    async def set_commission(self, value):
        if not 0 <= value <= 1_000_000_000:
            raise UserError('Komissiya 0–1 000 000 000 oralig‘ida bo‘lsin.')
        await self.run(lambda c: c.execute("UPDATE settings SET value=? WHERE key='commission'", (str(value),)).rowcount)

    async def debit(self, admin, driver_id, amount, key):
        if admin not in self.admins or not 0 < amount <= 1_000_000_000:
            raise UserError('Summa yoki ruxsat noto‘g‘ri.')
        def change(c):
            if one(c, 'SELECT 1 FROM ledger WHERE idempotency_key=?', (key,)):
                return False
            d = one(c, "SELECT * FROM drivers WHERE driver_id=? AND status='approved'", (driver_id,))
            if not d:
                raise UserError('Tasdiqlangan haydovchi topilmadi.')
            if c.execute("UPDATE drivers SET balance=balance-? WHERE driver_id=? AND status='approved' AND balance>=?",
                         (amount, driver_id, amount)).rowcount != 1:
                raise UserError('Balansda bu summa yo‘q. Kamroq summa kiriting yoki bekor qiling.')
            c.execute('INSERT INTO ledger(driver_id,amount,kind,idempotency_key,actor,created_at) VALUES(?,?,?,?,?,?)',
                      (driver_id, -amount, 'debit', key, admin, int(time.time())))
            enqueue(c, key, 'send', d['telegram_id'],
                    text=f"Admin balansingizdan {amount:,} so‘m ayirdi. Qoldiq: {d['balance']-amount:,} so‘m.")
            return True
        return await self.run(change)

    async def add_route(self, name):
        if not 3 <= len(name) <= 100:
            raise UserError('Yo‘nalish nomi 3–100 belgidan iborat bo‘lsin.')
        await self.run(lambda c: c.execute('INSERT INTO routes(route_name) VALUES(?) ON CONFLICT(route_name) '
                                           'DO UPDATE SET active=1', (name,)).rowcount)

    async def setting(self, key):
        rows = await self.fetch('SELECT value FROM settings WHERE key=?', (key,))
        return rows[0]['value'] if rows else ''

    async def set_setting(self, key, value):
        if key not in ('start_text', 'admin_contact'):
            raise UserError('Noto‘g‘ri sozlama.')
        await self.run(lambda c: c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value)).rowcount)

    async def save_route(self, rid, name, fare, description):
        if not 3 <= len(name) <= 100 or not 0 <= fare <= 1_000_000_000 or not 1 <= len(description) <= 500:
            raise UserError('Yo‘nalish, narx yoki tavsif noto‘g‘ri.')
        def save(c):
            try:
                if rid:
                    if c.execute('UPDATE routes SET route_name=?,fare=?,description=? WHERE id=? AND active=1',
                                 (name, fare, description, rid)).rowcount != 1:
                        raise UserError('Yo‘nalish topilmadi.')
                else:
                    c.execute('INSERT INTO routes(route_name,fare,description) VALUES(?,?,?) ON CONFLICT(route_name) '
                              'DO UPDATE SET fare=excluded.fare,description=excluded.description,active=1', (name, fare, description))
            except sqlite3.IntegrityError:
                raise UserError('Bunday nomli yo‘nalish mavjud.') from None
        await self.run(save)

    async def passenger_entry(self, uid, name):
        def save(c):
            if one(c, 'SELECT 1 FROM drivers WHERE telegram_id=? AND status IN (\'approved\',\'pending\')', (uid,)):
                raise UserError('Siz haydovchi sifatida ro‘yxatdan o‘tgansiz.')
            c.execute('INSERT INTO users VALUES(?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET role=excluded.role',
                      (uid, name[:100], '', 'passenger', int(time.time())))
        await self.run(save)

    async def remove_route(self, rid):
        await self.run(lambda c: c.execute('UPDATE routes SET active=0 WHERE id=?', (rid,)).rowcount)

    async def create_order(self, uid, rid, seats, desc, key, phone=None, note='', expected_route=None):
        if seats not in range(5) or len(note) > 500 or (seats == 0 and (not desc or not 1 <= len(desc) <= 500)):
            raise UserError('Buyurtma ma’lumotlari noto‘g‘ri.')
        def create(c):
            old = one(c, 'SELECT order_id FROM orders WHERE request_key=?', (key,))
            if old:
                return old['order_id']
            u = one(c, 'SELECT * FROM users WHERE telegram_id=?', (uid,))
            if not u or u['role'] != 'passenger':
                raise UserError('Avval yo‘lovchi sifatida ro‘yxatdan o‘ting.')
            if one(c, "SELECT 1 FROM orders WHERE passenger_id=? AND status='active'", (uid,)):
                raise UserError('Sizda faol buyurtma bor. /orders orqali ko‘ring yoki bekor qiling.')
            route = one(c, 'SELECT * FROM routes WHERE id=? AND active=1', (rid,))
            if not route:
                raise UserError('Bu yo‘nalish faol emas. /order orqali qayta tanlang.')
            if expected_route and [route['route_name'], route['fare'], route['description']] != expected_route:
                raise UserError('Yo‘nalish narxi yoki tavsifi yangilandi. Buyurtmani qayta boshlang.')
            contact = phone or u['phone']
            if not contact:
                raise UserError('Telefon raqamini qo‘lda kiriting.')
            fee = int(one(c, "SELECT value FROM settings WHERE key='commission'")['value']) * seats
            oid = c.execute('INSERT INTO orders(request_key,passenger_id,route_id,route,seats,mail_desc,commission,created_at) '
                            'VALUES(?,?,?,?,?,?,?,?)', (key, uid, rid, route['route_name'], seats, desc, fee, int(time.time()))).lastrowid
            c.execute('UPDATE orders SET fare=?,route_description=?,contact_phone=?,note=? WHERE order_id=?',
                      (route['fare'], route['description'], contact, note, oid))
            c.execute('UPDATE users SET phone=? WHERE telegram_id=?', (contact, uid))
            for d in c.execute("SELECT telegram_id FROM drivers WHERE status='approved'"):
                enqueue(c, f'order:{oid}:{d[0]}', 'order_card', d[0], order_id=oid)
            enqueue(c, f'order-created:{oid}', 'send', uid,
                    text=f'Buyurtma #{oid} qabul qilindi. Haydovchi olishi bilan xabar beramiz.\n«Buyurtmalarim» — holat')
            return oid
        return await self.run(create)

    async def claim(self, uid, oid):
        def take(c):
            o = one(c, 'SELECT * FROM orders WHERE order_id=?', (oid,))
            if not o or o['status'] != 'active':
                raise UserError('Bu zakaz allaqachon olingan yoki bekor qilingan.')
            d = one(c, DRIVER_SQL + ' WHERE telegram_id=?', (uid,))
            if not d or d['status'] != 'approved':
                raise UserError('Faqat tasdiqlangan haydovchilar zakaz olishi mumkin.')
            changed = c.execute("UPDATE drivers SET balance=balance-? WHERE id=? AND status='approved' AND balance>=?",
                                (o['commission'], d['id'], o['commission'])).rowcount
            if changed != 1:
                raise UserError('Balans yetarli emas. Adminga murojaat qiling.')
            changed = c.execute("UPDATE orders SET status='taken',driver_id=?,taken_at=? WHERE order_id=? AND status='active'",
                                (d['driver_id'], int(time.time()), oid)).rowcount
            if changed != 1:
                raise UserError('Bu zakaz allaqachon olindi.')
            c.execute('INSERT INTO ledger(driver_id,amount,kind,idempotency_key,actor,created_at) VALUES(?,?,?,?,?,?)',
                      (d['driver_id'], -o['commission'], 'commission', f'claim:{oid}', uid, int(time.time())))
            p = one(c, 'SELECT * FROM users WHERE telegram_id=?', (o['passenger_id'],))
            info = order_text(o)
            contact = f"Yo‘lovchi: {p['full_name']}\nTelefon: {o['contact_phone'] or p['phone']}"
            enqueue(c, f'claimed:{oid}:driver', 'send', uid, text=info + '\n' + contact)
            enqueue(c, f'claimed:{oid}:passenger', 'send', o['passenger_id'],
                    text=f'Buyurtma #{oid} olindi!\n' + driver_text(d))
            enqueue(c, f'claimed:{oid}:audit', 'send', self.orders_channel,
                    text=info + '\n' + contact + '\n\nHaydovchi:\n' + driver_text(d))
            self._close_cards(c, oid)
            return o
        return await self.run(take)

    @staticmethod
    def _close_cards(c, oid):
        for m in c.execute('SELECT * FROM order_messages WHERE order_id=?', (oid,)):
            enqueue(c, f"close:{oid}:{m['chat_id']}:{m['message_id']}", 'close_card', m['chat_id'],
                    order_id=oid, message_id=m['message_id'])

    async def record_card(self, oid, chat, mid):
        def save(c):
            c.execute('INSERT OR IGNORE INTO order_messages VALUES(?,?,?)', (oid, chat, mid))
            o = one(c, 'SELECT status FROM orders WHERE order_id=?', (oid,))
            if o['status'] != 'active':
                self._close_cards(c, oid)
        await self.run(save)

    async def cancel_order(self, uid, oid):
        def cancel(c):
            if c.execute("UPDATE orders SET status='cancelled' WHERE order_id=? AND passenger_id=? AND status='active'",
                         (oid, uid)).rowcount != 1:
                raise UserError('Faqat o‘zingizning hali olinmagan buyurtmangizni bekor qilishingiz mumkin.')
            self._close_cards(c, oid)
        await self.run(cancel)

    async def campaign_draft(self, admin, target, text):
        if admin not in self.admins or not 1 <= len(text) <= 3500:
            raise UserError('Xabar 1–3500 belgidan iborat bo‘lsin.')
        if target not in ('all', 'drivers', 'passengers'):
            rows = await self.fetch("SELECT 1 FROM drivers WHERE driver_id=? AND status='approved'", (target,))
            if not rows:
                raise UserError('Haydovchining Telegram ID raqami topilmadi.')
        token = uuid.uuid4().hex[:16]
        await self.run(lambda c: c.execute('INSERT INTO campaigns VALUES(?,?,?,?,?,?)',
                                           (token, admin, target, text, 'draft', int(time.time()))).rowcount)
        return token

    async def campaign_send(self, admin, token):
        if admin not in self.admins:
            raise UserError('Ruxsat yo‘q.')
        def send(c):
            draft = one(c, "SELECT * FROM campaigns WHERE token=? AND admin_id=? AND status='draft'", (token, admin))
            if not draft or draft['created_at'] < time.time() - 3600:
                raise UserError('Xabarnoma yuborilgan yoki tasdiqlash muddati tugagan.')
            target = draft['target']
            if target == 'all':
                rows = c.execute('SELECT telegram_id FROM users').fetchall()
            elif target == 'drivers':
                rows = c.execute("SELECT telegram_id FROM drivers WHERE status='approved'").fetchall()
            elif target == 'passengers':
                rows = c.execute("SELECT telegram_id FROM users WHERE role='passenger'").fetchall()
            else:
                rows = c.execute("SELECT telegram_id FROM drivers WHERE driver_id=? AND status='approved'", (target,)).fetchall()
            for r in rows:
                enqueue(c, f'campaign:{token}:{r[0]}', 'send', r[0], text=draft['text'])
            c.execute("UPDATE campaigns SET status='queued' WHERE token=?", (token,))
            return len(rows)
        return await self.run(send)

    async def stats(self, timezone):
        now = datetime.now(ZoneInfo(timezone))
        start = datetime.combine(now.date(), day_time(), now.tzinfo)
        lo, hi = int(start.timestamp()), int((start + timedelta(days=1)).timestamp())
        def read(c):
            scalar = lambda sql, args=(): c.execute(sql, args).fetchone()[0]
            return dict(visitors=scalar('SELECT COUNT(*) FROM visitors WHERE created_at>=? AND created_at<?', (lo, hi)),
                        registered=scalar('SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<?', (lo, hi)),
                        today_orders=scalar('SELECT COUNT(*) FROM orders WHERE created_at>=? AND created_at<?', (lo, hi)),
                        orders=scalar('SELECT COUNT(*) FROM orders'),
                        passengers=scalar("SELECT COUNT(*) FROM users WHERE role='passenger'"),
                        drivers=scalar("SELECT COUNT(*) FROM drivers WHERE status='approved'"),
                        balance=scalar('SELECT COALESCE(SUM(balance),0) FROM drivers'),
                        revenue=scalar("SELECT -COALESCE(SUM(amount),0) FROM ledger WHERE kind='commission'"))
        return await self.run(read, write=False)

    async def next_jobs(self, limit=10):
        def lease(c):
            rows = [dict(r) for r in c.execute("SELECT * FROM outbox WHERE status='pending' AND available_at<=? "
                                             "ORDER BY CASE kind WHEN 'close_card' THEN 0 WHEN 'send' THEN 1 ELSE 2 END,id LIMIT ?",
                                             (time.time(), limit))]
            for r in rows:
                c.execute("UPDATE outbox SET status='sending',attempts=attempts+1 WHERE id=?", (r['id'],))
                r['attempts'] += 1
            return rows
        return await self.run(lease)

    async def job_result(self, jid, status, delay=0, error=None):
        await self.run(lambda c: c.execute('UPDATE outbox SET status=?,available_at=?,last_error=? WHERE id=?',
                                           (status, time.time() + delay, error, jid)).rowcount)


def order_text(o):
    kind = f"{o['seats']} o‘rin" if o['seats'] else '📦 Pochta'
    text = f"🚖 Buyurtma #{o['order_id']}\nYo‘nalish: {o['route']}\n{kind}\nKomissiya: {o['commission']:,} so‘m"
    if not o['seats']:
        text += '\nTavsif: ' + o['mail_desc']
    fare = o.get('fare', 0)
    text += f'\nYo‘lkira: {fare:,} so‘m / kishi'
    if not o['seats']:
        text += '\nPochta yetkazish narxi haydovchi bilan kelishiladi.'
    if o.get('route_description'):
        text += '\nYo‘nalish tavsifi: ' + o['route_description']
    if o.get('note'):
        text += '\nBuyurtma izohi: ' + o['note']
    return text
