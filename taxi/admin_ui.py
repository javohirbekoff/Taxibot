import re
import uuid
from aiogram import F
from aiogram.fsm.state import State, StatesGroup
from .db import DRIVER_SQL, UserError
from .handlers import require_admin, text_value, money
from .keyboards import HOME, CANCEL, reply_menu, admin_menu, form_menu, routes_keyboard


class AdminForm(StatesGroup):
    start = State()
    contact = State()
    driver = State()
    amount = State()
    credit = State()
    commission = State()
    routes = State()
    route_pick = State()
    route_edit = State()
    route_name = State()
    route_fare = State()
    route_description = State()
    route_confirm = State()
    audience = State()
    mail = State()
    mail_confirm = State()
    retry = State()


def register_admin(router, db, config, home):
    async def driver_list(m, state, purpose, page=0):
        if purpose in ('credit', 'debit'):
            await state.set_state(AdminForm.driver)
            await state.update_data(purpose=purpose, driver_labels={}, page=0)
            heading = '💳 Balans to‘ldirish' if purpose == 'credit' else '➖ Balansdan ayirish'
            await m.answer(heading + '\n\nHaydovchining Telegram ID raqamini qo‘lda yozing.\n'
                           'Haydovchi o‘z ID raqamini «Balans ko‘rish» bo‘limidan oladi.', reply_markup=form_menu())
            return
        rows = await db.fetch(DRIVER_SQL + " WHERE status='approved' ORDER BY telegram_id")
        page = max(0, min(page, max(0, (len(rows)-1)//8)))
        labels = {f"{d['telegram_id']} · {d['full_name'][:25]}": str(d['telegram_id']) for d in rows[page*8:(page+1)*8]}
        await state.set_state(AdminForm.driver)
        await state.update_data(purpose=purpose, driver_labels=labels, page=page)
        keys = [[s] for s in labels]
        nav = []
        if page:
            nav.append('⬅️ Oldingi')
        if (page+1)*8 < len(rows):
            nav.append('Keyingi ➡️')
        if nav:
            keys.append(nav)
        keys.append([CANCEL, HOME])
        await m.answer('Haydovchini tanlang yoki Telegram ID raqamini yozing:' if rows else 'Tasdiqlangan haydovchi yo‘q.', reply_markup=reply_menu(keys))

    async def route_list(m, state, page=0):
        rows = await db.fetch('SELECT * FROM routes WHERE active=1 ORDER BY id')
        page = max(0, min(page, max(0, (len(rows)-1)//10)))
        await state.set_state(AdminForm.route_pick)
        await state.update_data(route_labels={r['route_name']: r['id'] for r in rows[page*10:(page+1)*10]}, page=page)
        await m.answer('Tahrirlash uchun yo‘nalishni tanlang:' if rows else 'Hozircha faol yo‘nalish yo‘q.', reply_markup=routes_keyboard(rows, page))

    async def route_preview(m, state):
        d = await state.get_data()
        await state.set_state(AdminForm.route_confirm)
        await m.answer(f"🗺 {d['name']}\n💵 {d['fare']:,} so‘m / kishi\n📝 {d['description']}",
                       reply_markup=reply_menu([['✅ Yo‘nalishni saqlash'], [CANCEL, HOME]]))

    labels = {'💳 Haydovchi balansini to‘ldirish', '➖ Balansdan ayirish', '💵 Komissiya', '🗺 Yo‘nalishlar', '📊 Statistika',
              '📝 Start xabarini tahrirlash', '👤 Admin lichkasini tahrirlash', '📢 Xabar yuborish', '📬 Xabarlar holati'}

    @router.message(F.text.in_(labels))
    async def action(m, state):
        require_admin(m.from_user.id, config)
        await state.clear()
        if m.text == '💳 Haydovchi balansini to‘ldirish':
            await driver_list(m, state, 'credit')
        elif m.text == '➖ Balansdan ayirish':
            await driver_list(m, state, 'debit')
        elif m.text == '💵 Komissiya':
            await state.set_state(AdminForm.commission)
            await m.answer(f"Bir kishi uchun komissiya: {await db.setting('commission')} so‘m.\nYangi summani tanlang yoki yozing:",
                           reply_markup=reply_menu([['0', '500', '1000'], [CANCEL, HOME]]))
        elif m.text == '📝 Start xabarini tahrirlash':
            await state.set_state(AdminForm.start)
            await m.answer('Hozirgi start xabari:\n' + await db.setting('start_text') + '\n\nYangi xabarni yozing:', reply_markup=form_menu())
        elif m.text == '👤 Admin lichkasini tahrirlash':
            await state.set_state(AdminForm.contact)
            await m.answer('Adminning @username yoki https://t.me/username manzilini kiriting:', reply_markup=form_menu())
        elif m.text == '🗺 Yo‘nalishlar':
            await state.set_state(AdminForm.routes)
            await m.answer('🗺 Yo‘nalishlarni boshqarish', reply_markup=reply_menu([['➕ Yo‘nalish qo‘shish'], ['✏️ Yo‘nalishni tahrirlash'], [HOME]]))
        elif m.text == '📊 Statistika':
            s = await db.stats(config.timezone)
            await m.answer(f"📊 Bugungi yangi foydalanuvchilar: {s['visitors']}\nBugungi zakazlar: {s['today_orders']}\n"
                           f"Jami zakazlar: {s['orders']}\nYo‘lovchilar: {s['passengers']}\nHaydovchilar: {s['drivers']}\n"
                           f"Jami balans: {s['balance']:,} so‘m\nKomissiya tushumi: {s['revenue']:,} so‘m", reply_markup=admin_menu())
        elif m.text == '📢 Xabar yuborish':
            await state.set_state(AdminForm.audience)
            await m.answer('Kimga yuboramiz?', reply_markup=reply_menu([['Haydovchilarga', 'Yo‘lovchilarga'], ['Barchaga', 'Bitta haydovchiga'], [CANCEL, HOME]]))
        elif m.text == '📬 Xabarlar holati':
            rows = await db.fetch('SELECT status,COUNT(*) n FROM outbox GROUP BY status')
            dead = await db.fetch("SELECT id FROM outbox WHERE status='dead' ORDER BY id DESC LIMIT 10")
            names = {'pending': 'Kutilmoqda', 'sending': 'Yuborilmoqda', 'done': 'Yuborilgan', 'dead': 'Xato'}
            await state.set_state(AdminForm.retry)
            await state.update_data(jobs=[str(r['id']) for r in dead])
            await m.answer('\n'.join(f"{names[r['status']]}: {r['n']}" for r in rows) or 'Navbat bo‘sh.',
                           reply_markup=reply_menu([[f"🔄 Qayta yuborish #{r['id']}"] for r in dead] + [[HOME]]))

    @router.message(AdminForm.start)
    async def edit_start(m, state):
        require_admin(m.from_user.id, config)
        await db.set_setting('start_text', text_value(m, 1, 3000))
        await home(m, state)

    @router.message(AdminForm.contact)
    async def edit_contact(m, state):
        require_admin(m.from_user.id, config)
        username = re.sub(r'^(?:@|https://t\.me/)', '', text_value(m, 5, 100))
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', username):
            raise UserError('To‘g‘ri @username kiriting. Masalan: @taxi_admin')
        await db.set_setting('admin_contact', 'https://t.me/' + username)
        await m.answer('✅ Admin aloqa manzili saqlandi.')
        await home(m, state)

    @router.message(AdminForm.commission)
    async def commission(m, state):
        require_admin(m.from_user.id, config)
        await db.set_commission(money(m))
        await m.answer('✅ Komissiya saqlandi. Pochta uchun komissiya 0 so‘m.')
        await home(m, state)

    @router.message(AdminForm.driver)
    async def pick_driver(m, state):
        require_admin(m.from_user.id, config)
        data = await state.get_data()
        if m.text in ('⬅️ Oldingi', 'Keyingi ➡️'):
            await driver_list(m, state, data['purpose'], data['page'] + (1 if m.text == 'Keyingi ➡️' else -1))
            return
        did = data['driver_labels'].get(m.text, (m.text or '').strip())
        d = await db.driver(int(did)) if did.isascii() and did.isdigit() else None
        if not d or d['status'] != 'approved':
            raise UserError('Tasdiqlangan haydovchining Telegram ID raqamini kiriting.')
        await state.update_data(driver_id=did, target=did)
        financial = data['purpose'] in ('credit', 'debit')
        await state.set_state(AdminForm.amount if financial else AdminForm.mail)
        prompt = 'Ayiriladigan summani yozing:' if data['purpose'] == 'debit' else 'Qo‘shiladigan summani tanlang yoki yozing:'
        await m.answer(f"{d['full_name']} · {did}\nBalans: {d['balance']:,} so‘m\n" +
                       (prompt if financial else 'Xabar matnini yozing:'),
                       reply_markup=reply_menu([['10000', '25000'], ['50000', '100000'], [CANCEL, HOME]]) if financial else form_menu())

    @router.message(AdminForm.amount)
    async def amount(m, state):
        require_admin(m.from_user.id, config)
        value = money(m, 1)
        await state.update_data(amount=value, token=uuid.uuid4().hex)
        await state.set_state(AdminForm.credit)
        d = await state.get_data()
        is_debit = d['purpose'] == 'debit'
        action = 'Ayiriladi' if is_debit else 'Qo‘shiladi'
        await m.answer(f"Telegram ID: {d['driver_id']}\n{action}: {value:,} so‘m\nTasdiqlaysizmi?",
                       reply_markup=reply_menu([['✅ Balansdan ayirish' if is_debit else '✅ Balansni to‘ldirish'], [CANCEL, HOME]]))

    @router.message(AdminForm.credit)
    async def credit(m, state):
        require_admin(m.from_user.id, config)
        d = await state.get_data()
        is_debit = d['purpose'] == 'debit'
        if m.text != ('✅ Balansdan ayirish' if is_debit else '✅ Balansni to‘ldirish'):
            raise UserError('Tasdiqlash yoki bekor qilish tugmasini bosing.')
        operation = db.debit if is_debit else db.topup
        await operation(m.from_user.id, d['driver_id'], d['amount'], 'ui:' + d['token'])
        await m.answer('✅ Balansdan summa ayirildi.' if is_debit else '✅ Balans to‘ldirildi.')
        await home(m, state)

    @router.message(AdminForm.routes)
    async def route_action(m, state):
        require_admin(m.from_user.id, config)
        if m.text == '➕ Yo‘nalish qo‘shish':
            await state.update_data(rid=None, mode='new')
            await state.set_state(AdminForm.route_name)
            await m.answer('Qayerdan → qayerga? Yo‘nalish nomini yozing:', reply_markup=form_menu())
        elif m.text == '✏️ Yo‘nalishni tahrirlash':
            await route_list(m, state)
        else:
            raise UserError('Pastdagi tugmani tanlang.')

    @router.message(AdminForm.route_pick)
    async def pick_route(m, state):
        require_admin(m.from_user.id, config)
        data = await state.get_data()
        if m.text in ('⬅️ Oldingi', 'Keyingi ➡️'):
            await route_list(m, state, data['page'] + (1 if m.text == 'Keyingi ➡️' else -1))
            return
        rows = await db.fetch('SELECT * FROM routes WHERE id=? AND active=1', (data['route_labels'].get(m.text),))
        if not rows:
            raise UserError('Pastdagi faol yo‘nalishni tanlang.')
        r = rows[0]
        await state.update_data(rid=r['id'], name=r['route_name'], fare=r['fare'], description=r['description'], mode='edit')
        await state.set_state(AdminForm.route_edit)
        await m.answer(f"{r['route_name']}\n{r['fare']:,} so‘m / kishi\n{r['description']}",
                       reply_markup=reply_menu([['✏️ Nomini tahrirlash', '💵 Narxini tahrirlash'], ['📝 Tavsifini tahrirlash'], ['🗑 Yo‘nalishni o‘chirish'], [HOME]]))

    @router.message(AdminForm.route_edit)
    async def route_edit(m, state):
        require_admin(m.from_user.id, config)
        fields = {'✏️ Nomini tahrirlash': (AdminForm.route_name, 'Yangi nomni yozing:'),
                  '💵 Narxini tahrirlash': (AdminForm.route_fare, 'Bir kishi uchun yangi narxni so‘mda yozing:'),
                  '📝 Tavsifini tahrirlash': (AdminForm.route_description, 'Yangi tavsifni yozing:')}
        if m.text in fields:
            st, prompt = fields[m.text]
            await state.set_state(st)
            await m.answer(prompt, reply_markup=form_menu())
        elif m.text == '🗑 Yo‘nalishni o‘chirish':
            await db.remove_route((await state.get_data())['rid'])
            await m.answer('Yo‘nalish o‘chirildi.')
            await home(m, state)
        else:
            raise UserError('Pastdagi tugmani tanlang.')

    @router.message(AdminForm.route_name)
    async def route_name(m, state):
        require_admin(m.from_user.id, config)
        value = text_value(m, 3, 100)
        if value in (HOME, CANCEL, '⬅️ Oldingi', 'Keyingi ➡️'):
            raise UserError('Boshqa nom kiriting.')
        await state.update_data(name=value)
        if (await state.get_data())['mode'] == 'new':
            await state.set_state(AdminForm.route_fare)
            await m.answer('Bir kishi uchun yo‘lkira qancha? So‘mda yozing. Masalan: 40000')
        else:
            await route_preview(m, state)

    @router.message(AdminForm.route_fare)
    async def route_fare(m, state):
        require_admin(m.from_user.id, config)
        await state.update_data(fare=money(m))
        if (await state.get_data())['mode'] == 'new':
            await state.set_state(AdminForm.route_description)
            await m.answer('Yo‘nalish tavsifini yozing. Masalan: Har bir odam boshiga 40 000 so‘m, markazdan olib ketamiz.')
        else:
            await route_preview(m, state)

    @router.message(AdminForm.route_description)
    async def route_description(m, state):
        require_admin(m.from_user.id, config)
        await state.update_data(description=text_value(m))
        await route_preview(m, state)

    @router.message(AdminForm.route_confirm)
    async def route_save(m, state):
        require_admin(m.from_user.id, config)
        if m.text != '✅ Yo‘nalishni saqlash':
            raise UserError('Saqlash tugmasini bosing.')
        d = await state.get_data()
        await db.save_route(d['rid'], d['name'], d['fare'], d['description'])
        await m.answer('✅ Yo‘nalish saqlandi.')
        await home(m, state)

    @router.message(AdminForm.audience)
    async def audience(m, state):
        require_admin(m.from_user.id, config)
        if m.text == 'Bitta haydovchiga':
            await driver_list(m, state, 'mail')
            return
        target = {'Haydovchilarga': 'drivers', 'Yo‘lovchilarga': 'passengers', 'Barchaga': 'all'}.get(m.text)
        if not target:
            raise UserError('Pastdagi auditoriya tugmasini tanlang.')
        await state.update_data(target=target)
        await state.set_state(AdminForm.mail)
        await m.answer('Xabar matnini yozing:', reply_markup=form_menu())

    @router.message(AdminForm.mail)
    async def mailing(m, state):
        require_admin(m.from_user.id, config)
        text = text_value(m, 1, 3000)
        token = await db.campaign_draft(m.from_user.id, (await state.get_data())['target'], text)
        await state.update_data(campaign=token)
        await state.set_state(AdminForm.mail_confirm)
        await m.answer('📢 Xabarni tekshiring:\n\n' + text, reply_markup=reply_menu([['✅ Xabarni yuborish'], [CANCEL, HOME]]))

    @router.message(AdminForm.mail_confirm)
    async def mail_send(m, state):
        require_admin(m.from_user.id, config)
        if m.text != '✅ Xabarni yuborish':
            raise UserError('Yuborish yoki bekor qilish tugmasini bosing.')
        n = await db.campaign_send(m.from_user.id, (await state.get_data())['campaign'])
        await m.answer(f'✅ {n} ta xabar navbatga qo‘shildi.')
        await home(m, state)

    @router.message(AdminForm.retry)
    async def retry(m, state):
        require_admin(m.from_user.id, config)
        jid = (m.text or '').split('#')[-1]
        if jid not in (await state.get_data())['jobs']:
            raise UserError('Pastdagi xabar tugmasini tanlang.')
        await db.run(lambda c: c.execute("UPDATE outbox SET status='pending',attempts=0,available_at=0 WHERE id=? AND status='dead'", (int(jid),)).rowcount)
        await m.answer('Qayta yuborish navbatiga qo‘shildi.')
