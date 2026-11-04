# Telegram Taxi & Post — tugmali versiya 3

Python 3.12+, aiogram 3.31, SQLite WAL. Asosiy menyular Telegramning pastki klaviaturasida. Buyurtmani olish va adminning haydovchini tasdiqlashi o‘sha xabarga biriktirilgan tugmalar orqali bajariladi.

## Yo‘lovchi

`/start` → **Yo‘lovchi** → **Taksi chaqirish** → admin kiritgan yo‘nalish → **1 kishi / 2 kishi / 3 kishi / 4 kishi / Pochta**.

Pochta tanlansa, tarkibi yoziladi. So‘ng har bir buyurtmada telefon **qo‘lda matn bilan** kiritiladi, buyurtma izohi yoziladi. Yakuniy tasdiqlashda yo‘nalish, admin belgilagan kishi boshiga yo‘lkira, yo‘nalish tavsifi, pochta tavsifi, izoh va telefon chiqadi. **Jami yo‘lkira chiqarilmaydi.** «Buyurtmani yuborish» bosilmaguncha haydovchilarga tarqatilmaydi.

Pochta uchun haydovchi komissiyasi 0. Pochta yetkazish narxi haydovchi bilan kelishiladi; avtomobil yo‘lkirasi pochta narxi sifatida hisoblanmaydi.

Tasdiqlangach, buyurtma barcha tasdiqlangan haydovchilarga navbat orqali yuboriladi. Telefon umumiy kartada ko‘rinmaydi; buyurtmani muvaffaqiyatli olgan haydovchiga beriladi. Boshqalarda «Zakaz olindi» chiqadi. Buyurtmalarim orqali holat va haydovchi ma’lumotlari ko‘riladi; hali olinmagan buyurtma bekor qilinadi.

## Haydovchi

Haydovchi faqat **ism-familiya → mashina nomi → davlat raqami → qo‘lda telefon → mashina rasmi**ni kiritadi. Tug‘ilgan yil so‘ralmaydi. Ma’lumotlar adminga foto bilan avtomatik yuboriladi. Admin o‘sha xabardagi «Tasdiqlash / Rad etish»ni bosadi. Adminning bosh menyusida «Haydovchi arizalari» yoki «Kutilayotgan arizalar» tugmasi yo‘q.

Haydovchi IDsi — **o‘zining Telegram ID raqami**. Alohida DRV raqam berilmaydi.

Telegram ID bosh menyu, balans va balans to‘ldirish xabarlarida nusxalashga qulay `code` formatida beriladi.

Tasdiqlangan haydovchining pastki menyusida faqat:

- **Balans ko‘rish** — balans va Telegram ID.
- **Balans to‘ldirish** — admin lichkasiga bosiladigan havola.

Yangi zakazlar avtomatik keladi. Balans zakaz komissiyasidan kam bo‘lsa, uni olish rad etiladi. Yo‘lkira va komissiya boshqa-boshqa: masalan, yo‘lkira 40 000 so‘m/kishi, komissiya 500 so‘m/kishi.

## Admin

`ADMIN_IDS` ro‘yxatidagi akkaunt `/start` bossa, boshqaruv menyusi chiqadi:

| Tugma | Amal |
|---|---|
| Haydovchi balansini to‘ldirish | Telegram IDni qo‘lda yozish → summa → tasdiqlash; haydovchilar ro‘yxati chiqmaydi |
| Balansdan ayirish | Telegram IDni qo‘lda yozish → musbat summa → ayirishni tasdiqlash |
| Komissiya | Har kishi uchun komissiyani belgilash |
| Yo‘nalishlar | Qo‘shish; nomi, narxi va tavsifini alohida tahrirlash; o‘chirish |
| Statistika | Bugungi/jami zakazlar, foydalanuvchilar, balans, komissiya |
| Start xabarini tahrirlash | `/start` va bosh menyu salomlashuvini o‘zgartirish |
| Admin lichkasini tahrirlash | `@username` yoki `https://t.me/username` kiritish |
| Xabar yuborish | Haydovchilar, yo‘lovchilar, barcha yoki bitta haydovchiga matn; yuborishdan oldin tasdiqlash |
| Xabarlar holati | Yuborilgan/kutilayotgan/xato xabarlar va qayta yuborish |

Yo‘nalish qo‘shish: **nom → kishi boshiga narx → tavsif → saqlash**. Misol: «Shirin ➡️ Toshkent», `40000`, «Odam boshiga 40 000 so‘m, markazdan olib ketamiz».

## O‘rnatish

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python bot.py
```

`bot.py` joylashgan papkadan ishga tushiring. `.env` mavjud bo‘lsa nusxalab ustidan yozmang.

| Sozlama | Mazmuni |
|---|---|
| BOT_TOKEN | BotFather tokeni |
| ADMIN_IDS | Adminlarning Telegram IDlari, vergul bilan |
| DRIVER_CHANNEL_ID | Haydovchilar maxfiy kanali, manfiy ID |
| ORDERS_CHANNEL_ID | Olingan zakazlar maxfiy kanali, manfiy ID |
| DB_PATH | Lokal: `data/bot.sqlite3`; Railway: `/data/bot.sqlite3` |
| TIMEZONE | `Asia/Tashkent` |
| DEFAULT_COMMISSION | Faqat yangi baza uchun boshlang‘ich komissiya |

Bot ikkala maxfiy kanalda admin bo‘lsin; haydovchilar kanalida taklif qilish huquqi ham kerak. Bot tasdiqlangan haydovchiga kanal taklif havolasini yuboradi va kirish so‘rovini bazadagi maqomga qarab tasdiqlaydi. Adminlar avval botga `/start` yuborishi kerak.

## Eski versiyadan yangilash

Botni **Ctrl+C** bilan to‘xtatib, loyiha kodini yangilang va `python bot.py` bilan qayta ishga tushiring. `.env` va `data/`ni almashtirmang.

Oldingi v1/v2 baza birinchi ishga tushishda avtomatik v3 ga ko‘chiriladi. Avval yoniga `bot.sqlite3.v1-backup` yoki `bot.sqlite3.v2-backup` zaxira nusxa yoziladi. Eski DRV IDlar, buyurtma va moliyaviy yozuvlardagi havolalar Telegram IDlarga o‘tkaziladi. Balans, foydalanuvchilar va tarix saqlanadi. Eski ro‘yxatdan o‘tish formasi tozalanadi — `/start` bilan qayta boshlang.

Admin ayirgan summa moliyaviy jurnalda `debit` sifatida alohida saqlanadi va komissiya tushumiga qo‘shilmaydi. Balans manfiy bo‘lishiga yo‘l qo‘yilmaydi; haydovchiga ayirilgan summa haqida xabar yuboriladi.

**Eski yo‘nalishlarga admin menyusidan narx va tavsif kiriting.** Tavsifi hali kiritilmagan eski yo‘nalish yo‘lovchi ro‘yxatida ko‘rinmaydi. Keyin start xabari va admin lichkasini sozlang.

## Railway

Repositorydan service yarating; Dockerfile va railway.toml tayyor. **Volume `/data`** ulang, `DB_PATH=/data/bot.sqlite3` belgilang. Bitta replica va ushbu token uchun bitta bot jarayoni ishlasin. Serverless/uxlatish o‘chirilgan bo‘lsin.

`RAILWAY_DEPLOYMENT_OVERLAP_SECONDS=0`, `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30` kiriting. Polling uchun ochiq port/domen kerak emas. Volume zaxira nusxalarini yoqing. Railway Volume redeployida qisqa uzilish bo‘lishi mumkin.

## Yaxlitlik va cheklovlar

- Buyurtma olish, balans yechish, moliyaviy jurnal va xabar navbati bir SQL tranzaksiyasida. Bir zakazga faqat bitta g‘olib.
- Telefon, yo‘lkira va tavsif buyurtmaning o‘zida saqlanadi. Keyingi o‘zgartirishlar oldingi buyurtmani o‘zgartirmaydi. Tasdiqlashdan oldin narx o‘zgarsa, buyurtmani qaytadan boshlash so‘raladi.
- Bitta yo‘lovchida bir vaqtda bitta olinmagan faol buyurtma.
- Xabarlar Telegram limitlariga mos navbatda yuboriladi. Yetkazish mutlaqo bir vaqtning o‘zida bo‘lmaydi. Eski kartadagi tugma yopilishdan oldin bosilsa ham, baza ikkinchi haydovchini rad etadi.
- Telegramga xabar yuborilib, natija yozilishidan oldin jarayon uzilsa, xabar takror kelishi mumkin. Zakaz va komissiya takror hisoblanmaydi.
- Telefon umumiy kartaga qo‘shilmaydi. Foydalanuvchi telefonni o‘zi izoh yoki pochta tavsifiga yozsa, matnning o‘sha qismi kartada ko‘rinadi.
- SQLite faylini ko‘p server o‘rtasida bo‘lishmang. WAL bazadan ishlayotgan paytda nusxa olish uchun SQLite backup API yoki Railway Volume backupdan foydalaning.
- Eski slash buyruqlar o‘rniga tugmali boshqaruv ishlatiladi; `/start` bosh menyuni ochadi.

## Testlar

```sh
python -m unittest discover -s tests -v
```

Telegram javoblari testlarda almashtiriladi. Haqiqiy Telegramda foydalanuvchi/ikki haydovchi, admin tasdig‘i, ikkita kanal, balans, takror zakaz olish va qayta ishga tushishni tekshiring. Ushbu yetkazib berishda jonli Telegramga xabar yuborilmadi va Railway deploy qilinmadi.
