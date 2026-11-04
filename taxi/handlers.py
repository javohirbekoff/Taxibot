import logging
import html
import re
import uuid

from aiogram import BaseMiddleware, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from .db import DRIVER_SQL, UserError, driver_text, order_text
from .keyboards import HOME, CANCEL, ADMIN, buttons, reply_menu, main_menu, admin_menu, form_menu, seats_keyboard, routes_keyboard


class Registration(StatesGroup):
    name = State()
    car = State()
    photo = State()
    plate = State()
    phone = State()


class Booking(StatesGroup):
    route = State()
    seats = State()
    description = State()
    phone = State()
    note = State()
    confirm = State()


def require_admin(uid, config):
    if uid not in config.admins:
        raise UserError('Bu bo‘lim faqat admin uchun.')


def text_value(m, lo=1, hi=500):
    value = (m.text or '').strip()
    if not lo <= len(value) <= hi or value.startswith('/'):
        raise UserError(f'{lo}–{hi} belgidan iborat matn kiriting.')
    return value


def phone_value(m):
    value = re.sub(r'[\s()-]', '', text_value(m, 7, 30))
    if re.fullmatch(r'[0-9]{9}', value):
        value = '+998' + value
    elif re.fullmatch(r'998[0-9]{9}', value):
        value = '+' + value
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', value):
        raise UserError('Telefonni qo‘lda yozing. Masalan: +998901234567')
    return value


def money(m, minimum=0):
    value = text_value(m, 1, 20).replace(' ', '')
    if not re.fullmatch(r'[0-9]+', value) or not minimum <= int(value) <= 1_000_000_000:
        raise UserError('Summani so‘mda, faqat raqam bilan kiriting.')
    return int(value)


class Guard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        m = event.message if isinstance(event, CallbackQuery) else event
        if not isinstance(m, Message) or m.chat.type != 'private':
            return
        try:
            return await handler(event, data)
        except UserError as e:
            if isinstance(event, CallbackQuery):
                await event.answer(str(e), show_alert=True)
            else:
                await event.answer(str(e))
        except Exception as e:
            logging.getLogger(__name__).error('Handler failure: %s', type(e).__name__)
            try:
                await m.answer('Vaqtinchalik xatolik. Qayta urinib ko‘ring yoki /start ni bosing.')
            except TelegramAPIError:
                pass


def make_router(db, config):
    router = Router()
    router.message.outer_middleware(Guard())
    router.callback_query.outer_middleware(Guard())

    async def home(m, state, uid=None):
        uid = uid or m.from_user.id
        await state.clear()
        u, d = await db.user(uid), await db.driver(uid)
        greeting = html.escape(await db.setting('start_text'))
        if d and d['status'] == 'approved':
            greeting += f'\n\n🆔 Sizning Telegram ID: <code>{uid}</code>'
        await m.answer(greeting, parse_mode='HTML', reply_markup=main_menu(
            u['role'] if u else None, bool(d and d['status'] == 'approved'), uid in config.admins))

    async def route_list(m, state, page=0):
        rows = await db.fetch("SELECT * FROM routes WHERE active=1 AND description!='' ORDER BY id")
        page = max(0, min(page, max(0, (len(rows)-1)//10)))
        await state.set_state(Booking.route)
        await state.update_data(route_labels={r['route_name']: r['id'] for r in rows[page*10:(page+1)*10]}, page=page)
        await m.answer('📍 Qayerdan qayerga borasiz? Yo‘nalishni tanlang:' if rows else 'Hozircha faol yo‘nalish yo‘q.',
                       reply_markup=routes_keyboard(rows, page))

    @router.message(Command('start', 'cancel', 'help', 'admin'))
    async def start(m, state):
        await db.visit(m.from_user.id)
        await home(m, state)

    @router.message(F.text.in_({HOME, CANCEL, ADMIN}))
    async def escape(m, state):
        data = await state.get_data()
        if data.get('campaign'):
            await db.run(lambda c: c.execute("UPDATE campaigns SET status='cancelled' WHERE token=? AND admin_id=? AND status='draft'",
                                              (data['campaign'], m.from_user.id)).rowcount)
        await home(m, state)

    @router.message(F.text == '🧍 Yo‘lovchi')
    async def choose_passenger(m, state):
        await db.passenger_entry(m.from_user.id, m.from_user.full_name)
        await home(m, state)

    @router.message(F.text == '🚖 Haydovchi')
    async def choose_driver(m, state):
        d = await db.driver(m.from_user.id)
        if d and d['status'] != 'rejected':
            await home(m, state)
            return
        await state.clear()
        await state.set_state(Registration.name)
        await m.answer('Ism va familiyangizni yozing:', reply_markup=form_menu())

    @router.message(F.text == '🔄 Holatni tekshirish')
    async def check(m, state):
        d = await db.driver(m.from_user.id)
        if d and d['status'] == 'pending':
            await m.answer('Ma’lumotlaringiz admin tasdig‘ini kutmoqda.')
        elif d and d['status'] == 'rejected':
            await state.clear()
            await m.answer('Tasdiqlanmadi. Qayta topshirishingiz mumkin.', reply_markup=main_menu())
            return
        await home(m, state)

    @router.message(F.text.in_({'💰 Balans ko‘rish', '💳 Balans to‘ldirish'}))
    async def balance(m, state):
        d = await db.driver(m.from_user.id)
        if not d or d['status'] != 'approved':
            raise UserError('Avval haydovchi sifatida tasdiqlanishingiz kerak.')
        await state.clear()
        if m.text == '💰 Balans ko‘rish':
            await m.answer(f"💰 Balans: {d['balance']:,} so‘m\nTelegram ID: <code>{m.from_user.id}</code>", parse_mode='HTML', reply_markup=main_menu('driver', True))
        else:
            contact = await db.setting('admin_contact')
            if not contact:
                raise UserError('Admin aloqa manzilini hali kiritmagan.')
            await m.answer(f'💳 Balansni to‘ldirish uchun adminga yozing.\nTelegram ID: <code>{m.from_user.id}</code>\n\n'
                           f'<a href="{html.escape(contact, quote=True)}">👤 Admin lichkasini ochish</a>',
                           parse_mode='HTML', reply_markup=main_menu('driver', True))

    @router.message(F.text == '🚖 Taksi chaqirish')
    async def book(m, state):
        u = await db.user(m.from_user.id)
        if not u or u['role'] != 'passenger':
            raise UserError('Avval «Yo‘lovchi»ni tanlang.')
        await state.clear()
        await route_list(m, state)

    @router.message(F.text == '📋 Buyurtmalarim')
    async def orders(m, state):
        await state.clear()
        rows = await db.fetch('SELECT * FROM orders WHERE passenger_id=? ORDER BY order_id DESC LIMIT 10', (m.from_user.id,))
        if not rows:
            await m.answer('Buyurtmalar yo‘q.')
        for o in rows:
            text = order_text(o) + '\nHolat: ' + {'active': 'Kutilmoqda', 'taken': 'Olindi', 'cancelled': 'Bekor qilindi'}[o['status']]
            if o['status'] == 'taken':
                d = (await db.fetch(DRIVER_SQL + ' WHERE driver_id=?', (o['driver_id'],)))[0]
                text += '\n' + driver_text(d)
            await m.answer(text, reply_markup=buttons([[('❌ Buyurtmani bekor qilish', f"cancel:{o['order_id']}")]]) if o['status'] == 'active' else None)

    from .admin_ui import register_admin
    register_admin(router, db, config, home)

    @router.message(Registration.name)
    async def reg_name(m, state):
        await state.update_data(name=text_value(m, 3, 100))
        await state.set_state(Registration.car)
        await m.answer('Mashina nomini yozing:')

    @router.message(Registration.car)
    async def reg_car(m, state):
        await state.update_data(car=text_value(m, 2, 100))
        await state.set_state(Registration.plate)
        await m.answer('Davlat raqamini yozing:')

    @router.message(Registration.photo)
    async def reg_photo(m, state):
        if not m.photo:
            raise UserError('Mashina rasmini foto sifatida yuboring.')
        await state.update_data(photo=m.photo[-1].file_id)
        await db.register(m.from_user.id, await state.get_data(), 'driver')
        await m.answer('✅ Ma’lumotlaringiz adminga yuborildi. Tasdiqlanishini kuting.')
        await home(m, state)

    @router.message(Registration.plate)
    async def reg_plate(m, state):
        value = text_value(m, 5, 20).upper()
        if not re.fullmatch(r'[A-Z0-9 -]+', value) or not any(c.isdigit() for c in value):
            raise UserError('Davlat raqami lotin harflari va raqamlardan iborat bo‘lsin.')
        await state.update_data(plate=value)
        await state.set_state(Registration.phone)
        await m.answer('Telefon raqamingizni qo‘lda yozing:')

    @router.message(Registration.phone)
    async def reg_phone(m, state):
        await state.update_data(phone=phone_value(m))
        await state.set_state(Registration.photo)
        await m.answer('Mashina rasmini foto sifatida yuboring:')

    @router.message(Booking.route, F.text)
    async def pick_route(m, state):
        data = await state.get_data()
        if m.text in ('⬅️ Oldingi', 'Keyingi ➡️'):
            await route_list(m, state, data['page'] + (1 if m.text == 'Keyingi ➡️' else -1))
            return
        rid = data['route_labels'].get(m.text)
        rows = await db.fetch('SELECT * FROM routes WHERE id=? AND active=1', (rid,))
        if not rows:
            raise UserError('Pastdagi faol yo‘nalishni tanlang.')
        r = rows[0]
        await state.update_data(rid=r['id'], name=r['route_name'], fare=r['fare'], description=r['description'])
        await state.set_state(Booking.seats)
        await m.answer('Necha kishi yoki pochta?', reply_markup=seats_keyboard())

    @router.message(Booking.seats)
    async def seats(m, state):
        n = {'1 kishi': 1, '2 kishi': 2, '3 kishi': 3, '4 kishi': 4, '📦 Pochta': 0}.get(m.text)
        if n is None:
            raise UserError('1–4 kishi yoki pochta tugmasini tanlang.')
        await state.update_data(seats=n, mail_desc=None)
        await state.set_state(Booking.description if n == 0 else Booking.phone)
        await m.answer('Pochta nimaligini yozing:' if n == 0 else 'Telefon raqamingizni qo‘lda yozing. Masalan: +998901234567', reply_markup=form_menu())

    @router.message(Booking.description)
    async def post_desc(m, state):
        await state.update_data(mail_desc=text_value(m))
        await state.set_state(Booking.phone)
        await m.answer('Telefon raqamingizni qo‘lda yozing. Masalan: +998901234567')

    @router.message(Booking.phone)
    async def booking_phone(m, state):
        await state.update_data(phone=phone_value(m))
        await state.set_state(Booking.note)
        await m.answer('Buyurtma izohini yozing: qayerdan olish kerak yoki boshqa kerakli ma’lumot.\nTelefon raqamini izohda takrorlamang.')

    @router.message(Booking.note)
    async def note(m, state):
        await state.update_data(note=text_value(m), token=uuid.uuid4().hex)
        d = await state.get_data()
        preview = dict(order_id='—', route=d['name'], seats=d['seats'], mail_desc=d['mail_desc'], commission=0,
                       fare=d['fare'], route_description=d['description'], note=d['note'])
        await state.set_state(Booking.confirm)
        text = order_text(preview).replace('\nKomissiya: 0 so‘m', '')
        await m.answer(text + '\n📞 Telefon: ' + d['phone'] + '\n\nBuyurtmani yuboramizmi?',
                       reply_markup=reply_menu([['✅ Buyurtmani yuborish'], [CANCEL, HOME]]))

    @router.message(Booking.confirm)
    async def confirm(m, state):
        if m.text != '✅ Buyurtmani yuborish':
            raise UserError('Yuborish yoki bekor qilish tugmasini bosing.')
        d = await state.get_data()
        oid = await db.create_order(m.from_user.id, d['rid'], d['seats'], d['mail_desc'], 'booking:' + d['token'],
                                    phone=d['phone'], note=d['note'], expected_route=[d['name'], d['fare'], d['description']])
        await m.answer(f'✅ Buyurtma #{oid} haydovchilarga yuborilmoqda.')
        await home(m, state)

    @router.callback_query(F.data.startswith('mod:'))
    async def moderate(q):
        require_admin(q.from_user.id, config)
        _, action, did, rev = q.data.split(':')
        if action not in ('yes', 'no'):
            raise UserError('Noto‘g‘ri amal.')
        await db.moderate(q.from_user.id, int(did), int(rev), action == 'yes')
        await q.answer('Tasdiqlandi.' if action == 'yes' else 'Rad etildi.')
        await q.message.edit_reply_markup(reply_markup=None)

    @router.callback_query(F.data.startswith('take:'))
    async def take(q):
        await db.claim(q.from_user.id, int(q.data.split(':')[1]))
        await q.answer('Zakaz sizniki! Mijoz telefon raqami yuboriladi.', show_alert=True)

    @router.callback_query(F.data.startswith('cancel:'))
    async def cancel(q):
        await db.cancel_order(q.from_user.id, int(q.data.split(':')[1]))
        await q.answer('Bekor qilindi.')
        await q.message.edit_reply_markup(reply_markup=None)

    @router.callback_query()
    async def stale(q):
        await q.answer('Zakaz olindi yoki bu tugma eskirgan.', show_alert=True)

    @router.chat_join_request()
    async def join(request):
        if request.chat.id == config.driver_channel:
            d = await db.driver(request.from_user.id)
            await (request.approve() if d and d['status'] == 'approved' else request.decline())

    @router.message()
    async def fallback(m, state):
        if await state.get_state():
            await m.answer('Pastdagi tugmani tanlang yoki so‘ralgan ma’lumotni matn bilan kiriting.')
        else:
            await home(m, state)

    return router
