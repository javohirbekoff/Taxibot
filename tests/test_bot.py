import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User

from taxi.db import Database
from taxi.handlers import Booking, Registration, make_router
from taxi.keyboards import ADMIN, CANCEL, HOME, main_menu, routes_keyboard, seats_keyboard
from taxi.storage import SQLiteStorage
from taxi.worker import OutboxWorker


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if method.__api_method__ in ('sendMessage', 'sendPhoto', 'editMessageReplyMarkup'):
            return Message(message_id=len(self.calls), date=datetime.now(timezone.utc),
                           chat=Chat(id=int(method.chat_id), type='private'),
                           from_user=User(id=bot.id, is_bot=True, first_name='Bot'),
                           text=getattr(method, 'text', None)).as_(bot)
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        if False:
            yield b''


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'bot.sqlite3', (999,))
        await self.db.init()
        self.cfg = SimpleNamespace(admins=(999,), timezone='Asia/Tashkent', driver_channel=-1)
        self.session = FakeSession()
        self.bot = Bot('123456:FAKE_TOKEN_FOR_OFFLINE_TESTS_ONLY', session=self.session)
        self.storage = SQLiteStorage(self.db)
        self.dp = Dispatcher(storage=self.storage, events_isolation=SimpleEventIsolation())
        self.dp.include_router(make_router(self.db, self.cfg))
        self.counter = 0

    async def asyncTearDown(self):
        await self.dp.fsm.close()
        await self.bot.session.close()
        self.tmp.cleanup()

    async def message(self, text=None, uid=1, photo=False):
        self.counter += 1
        m = dict(message_id=self.counter, date=int(datetime.now().timestamp()),
                 chat=dict(id=uid, type='private'), from_user=dict(id=uid, is_bot=False, first_name='User'))
        if text:
            m['text'] = text
            if text.startswith('/'):
                m['entities'] = [dict(type='bot_command', offset=0, length=len(text.split()[0]))]
        if photo:
            m['photo'] = [dict(file_id='PHOTO', file_unique_id='PHOTO_UNIQUE', width=800, height=600)]
        await self.dp.feed_update(self.bot, Update(update_id=self.counter, message=Message.model_validate(m)))

    async def callback(self, data, uid=1):
        self.counter += 1
        payload = dict(update_id=self.counter, callback_query=dict(id=str(self.counter),
                       from_user=dict(id=uid, is_bot=False, first_name='User'), chat_instance='test', data=data,
                       message=dict(message_id=10, date=int(datetime.now().timestamp()),
                                    chat=dict(id=uid, type='private'), text='Keyboard')))
        await self.dp.feed_update(self.bot, Update.model_validate(payload))

    def key(self, uid=1):
        return StorageKey(bot_id=self.bot.id, chat_id=uid, user_id=uid)

    def last_text(self):
        return next((x.text for x in reversed(self.session.calls) if hasattr(x, 'text')), '')

    async def approved(self, uid=100):
        await self.db.register(uid, dict(name='Driver Name', phone='+998901234567', year=1990,
                                        car='Gentra', plate='20 A 777 AA', photo='photo'), 'driver')
        d = await self.db.driver(uid)
        await self.db.moderate(999, d['id'], d['revision'], True)
        return str(uid)

    async def begin_booking(self, kind='2 kishi'):
        await self.db.save_route(None, 'Shirin ➡️ Bekobod', 40000, 'Odam boshiga 40 000 so‘m')
        for text in ('/start', '🧍 Yo‘lovchi', '🚖 Taksi chaqirish', 'Shirin ➡️ Bekobod', kind):
            await self.message(text)

    async def test_passenger_phone_note_fare_and_confirmation(self):
        await self.begin_booking()
        await self.message(photo=True)
        self.assertEqual(await self.storage.get_state(self.key()), Booking.phone.state)
        await self.message('901234567')
        await self.message('Markazdan olib keting')
        preview = self.last_text()
        self.assertNotIn('80,000', preview)
        self.assertNotIn('Jami yo‘lkira', preview)
        self.assertIn('40 000', preview)
        self.assertIn('+998901234567', preview)
        self.assertFalse(await self.db.fetch('SELECT * FROM orders'))
        await self.message('✅ Buyurtmani yuborish')
        await self.message('✅ Buyurtmani yuborish')
        rows = await self.db.fetch('SELECT * FROM orders')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['fare'], 40000)
        self.assertEqual(rows[0]['contact_phone'], '+998901234567')
        self.assertEqual(rows[0]['note'], 'Markazdan olib keting')

    async def test_post_flow_and_exactly_five_buttons(self):
        labels = [b.text for row in seats_keyboard().keyboard for b in row]
        self.assertEqual(labels, ['1 kishi', '2 kishi', '3 kishi', '4 kishi', '📦 Pochta'])
        await self.begin_booking('📦 Pochta')
        await self.message('Hujjatlar')
        await self.message('901234567')
        await self.message('Bekatdan oling')
        await self.message('✅ Buyurtmani yuborish')
        o = (await self.db.fetch('SELECT * FROM orders'))[0]
        self.assertEqual(o['seats'], 0)
        self.assertEqual(o['commission'], 0)
        self.assertEqual(o['mail_desc'], 'Hujjatlar')

    async def test_driver_registration_id_and_exactly_two_buttons(self):
        for text in ('/start', '🚖 Haydovchi', 'Driver Name', 'Gentra'):
            await self.message(text, uid=100)
        await self.message('20 A 777 AA', uid=100)
        await self.message('901234567', uid=100)
        await self.message(uid=100, photo=True)
        d = await self.db.driver(100)
        await self.callback(f"mod:yes:{d['id']}:1", uid=999)
        self.assertEqual((await self.db.driver(100))['driver_id'], '100')
        await self.message('/start', uid=100)
        markup = self.session.calls[-1].reply_markup
        self.assertEqual([b.text for row in markup.keyboard for b in row], ['💰 Balans ko‘rish', '💳 Balans to‘ldirish'])
        self.assertIn('<code>100</code>', self.last_text())

    async def test_start_and_admin_contact_edit(self):
        await self.message('📝 Start xabarini tahrirlash', uid=999)
        await self.message('Yangi salomlashuv!', uid=999)
        await self.message('/start')
        self.assertEqual(self.last_text(), 'Yangi salomlashuv!')
        await self.message('👤 Admin lichkasini tahrirlash', uid=999)
        await self.message('@taxi_admin', uid=999)
        await self.approved()
        await self.message('💳 Balans to‘ldirish', uid=100)
        self.assertIn('https://t.me/taxi_admin', self.session.calls[-1].text)
        self.assertEqual(sum(len(row) for row in self.session.calls[-1].reply_markup.keyboard), 2)

    async def test_route_add_and_each_field_edit(self):
        for text in ('🗺 Yo‘nalishlar', '➕ Yo‘nalish qo‘shish', 'A ➡️ B', '40000', 'Odam boshiga', '✅ Yo‘nalishni saqlash'):
            await self.message(text, uid=999)
        for action, value in [('💵 Narxini tahrirlash', '50000'), ('📝 Tavsifini tahrirlash', 'Yangi tavsif'), ('✏️ Nomini tahrirlash', 'B ➡️ C')]:
            for text in ('🗺 Yo‘nalishlar', '✏️ Yo‘nalishni tahrirlash', 'A ➡️ B', action, value, '✅ Yo‘nalishni saqlash'):
                await self.message(text, uid=999)
        r = (await self.db.fetch('SELECT * FROM routes'))[0]
        self.assertEqual((r['route_name'], r['fare'], r['description']), ('B ➡️ C', 50000, 'Yangi tavsif'))

    async def test_telegram_id_topup_confirmation_and_cancel(self):
        await self.approved()
        for text in ('💳 Haydovchi balansini to‘ldirish', '100', '50000'):
            await self.message(text, uid=999)
        self.assertEqual((await self.db.driver(100))['balance'], 0)
        await self.message('✅ Balansni to‘ldirish', uid=999)
        await self.message('✅ Balansni to‘ldirish', uid=999)
        self.assertEqual((await self.db.driver(100))['balance'], 50000)
        for text in ('💳 Haydovchi balansini to‘ldirish', '100', '25000', CANCEL, '✅ Balansni to‘ldirish'):
            await self.message(text, uid=999)
        self.assertEqual((await self.db.driver(100))['balance'], 50000)

    async def test_non_admin_cannot_edit_settings_or_moderate(self):
        await self.message('📝 Start xabarini tahrirlash')
        self.assertIsNone(await self.storage.get_state(self.key()))
        await self.message('👤 Admin lichkasini tahrirlash')
        self.assertIsNone(await self.storage.get_state(self.key()))
        await self.callback('mod:yes:1:1')
        self.assertIn('faqat admin', self.session.calls[-1].text)

    async def test_mailing_cancel_and_send(self):
        await self.message('🧍 Yo‘lovchi')
        for text in ('📢 Xabar yuborish', 'Barchaga', 'Salom', CANCEL, '✅ Xabarni yuborish'):
            await self.message(text, uid=999)
        self.assertFalse(await self.db.fetch("SELECT * FROM outbox WHERE dedup_key LIKE 'campaign:%'"))
        for text in ('📢 Xabar yuborish', 'Barchaga', 'Salom', '✅ Xabarni yuborish'):
            await self.message(text, uid=999)
        self.assertEqual(len(await self.db.fetch("SELECT * FROM outbox WHERE dedup_key LIKE 'campaign:%'")), 1)

    async def test_fsm_persists(self):
        await self.storage.set_state(self.key(), Booking.phone)
        await self.storage.set_data(self.key(), {'fare': 40000})
        recovered = SQLiteStorage(Database(self.db.path))
        self.assertEqual(await recovered.get_state(self.key()), Booking.phone.state)
        self.assertEqual(await recovered.get_data(self.key()), {'fare': 40000})

    async def test_worker_retry_and_approval_keyboard(self):
        await self.approved()
        jobs = await self.db.next_jobs(30)
        job = next(j for j in jobs if j['dedup_key'].endswith(':user'))
        worker = OutboxWorker(self.bot, self.db, self.cfg)
        await worker.process(job)
        self.assertEqual(len([b for row in self.session.calls[-1].reply_markup.keyboard for b in row]), 2)
        worker.deliver = AsyncMock(side_effect=TelegramRetryAfter(method=SendMessage(chat_id=1, text='test'), message='wait', retry_after=5))
        await worker.process(job)
        self.assertEqual((await self.db.fetch('SELECT status FROM outbox WHERE id=?', (job['id'],)))[0]['status'], 'pending')

    async def test_menu_exit_does_not_become_user_data(self):
        await self.message('🚖 Haydovchi')
        await self.message(HOME)
        self.assertIsNone(await self.storage.get_state(self.key()))
        self.assertIsNone(await self.db.user(1))

    async def test_no_application_buttons_on_admin_keyboard(self):
        await self.message('/start', uid=999)
        labels = [b.text for row in self.session.calls[-1].reply_markup.keyboard for b in row]
        self.assertFalse(any('ariza' in x.lower() for x in labels))

    async def test_admin_deduction_requires_confirmation_and_deduplicates(self):
        await self.approved()
        await self.db.topup(999, '100', 50000, 'seed')
        for text in ('➖ Balansdan ayirish', '100', '10000'):
            await self.message(text, uid=999)
        self.assertEqual((await self.db.driver(100))['balance'], 50000)
        await self.message('✅ Balansdan ayirish', uid=999)
        await self.message('✅ Balansdan ayirish', uid=999)
        self.assertEqual((await self.db.driver(100))['balance'], 40000)
        await self.message('➖ Balansdan ayirish', uid=1)
        self.assertIsNone(await self.storage.get_state(self.key(1)))

