from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

HOME = '🏠 Bosh menyu'
CANCEL = '❌ Bekor qilish'
ADMIN = '⚙️ Admin paneli'


def buttons(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=v) for t, v in row] for row in rows])


def reply_menu(rows):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
                               resize_keyboard=True, is_persistent=True)


def main_menu(role=None, approved=False, admin=False):
    if admin:
        return admin_menu()
    if role == 'driver' and approved:
        return reply_menu([['💰 Balans ko‘rish', '💳 Balans to‘ldirish']])
    if role == 'driver':
        return reply_menu([['🔄 Holatni tekshirish']])
    if role == 'passenger':
        return reply_menu([['🚖 Taksi chaqirish'], ['📋 Buyurtmalarim']])
    return reply_menu([['🧍 Yo‘lovchi', '🚖 Haydovchi']])


def admin_menu():
    return reply_menu([['💳 Haydovchi balansini to‘ldirish', '💵 Komissiya'],
                       ['➖ Balansdan ayirish'],
                       ['🗺 Yo‘nalishlar', '📊 Statistika'],
                       ['📝 Start xabarini tahrirlash', '👤 Admin lichkasini tahrirlash'],
                       ['📢 Xabar yuborish', '📬 Xabarlar holati']])


def form_menu():
    return reply_menu([[CANCEL, HOME]])


def seats_keyboard():
    return reply_menu([['1 kishi', '2 kishi'], ['3 kishi', '4 kishi'], ['📦 Pochta']])


def routes_keyboard(routes, page=0):
    labels = [r['route_name'] for r in routes[page * 10:(page + 1) * 10]]
    rows = [labels[i:i+2] for i in range(0, len(labels), 2)]
    nav = []
    if page:
        nav.append('⬅️ Oldingi')
    if (page + 1) * 10 < len(routes):
        nav.append('Keyingi ➡️')
    if nav:
        rows.append(nav)
    rows.append([HOME])
    return reply_menu(rows)
