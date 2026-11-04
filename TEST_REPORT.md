# Tekshiruv — v3

2026-11-04. Python 3.12.14, aiogram 3.31.0.

33 ta avtomatik test o‘tdi (45.163 soniya). Tekshiruvlar:

- Tug‘ilgan yilsiz ro‘yxatdan o‘tish: ism, mashina, raqam, telefon va oxirida rasm.
- Jami yo‘lkira chiqmasligi va Telegram IDning nusxalash uchun code formatida ko‘rinishi.
- Admin ayirishining tasdiqlanishi, takroriy bosishda bir marta yechish, yetarli bo‘lmagan balans va begona foydalanuvchini rad etish.
- Admin ayirishi bilan zakaz olish bir vaqtda sodir bo‘lganda balans manfiy bo‘lmasligi; ayirish komissiya tushumiga kirmasligi.

- Yo‘lovchini bir tugmada tanlash, qo‘lda telefon, izoh, yo‘lkira ko‘rsatilgan tasdiqlash.
- Aynan 5 ta o‘rin/pochta tugmasi; pochta oqimi va 0 komissiya.
- Telegram ID asosidagi haydovchi va aynan 2 ta asosiy tugma.
- Start xabari va admin aloqa manzilini tahrirlash.
- Yo‘nalish yaratish hamda nom, narx va tavsifni alohida tahrirlash.
- Balansni tasdiqlash, bekor qilish, takror bosishdan himoya.
- Admin huquqlari, xabarnoma tasdig‘i, FSM va navbatning qayta tiklanishi.
- Bir zakazga 30 parallel urinishda bitta g‘olib va bitta komissiya.
- Parallel zakazlarda balans manfiy bo‘lmasligi va sun’iy xatolikda rollback.
- Barcha tasdiqlangan haydovchilarga tarqatish; kontaktni umumiy payloadga kiritmaslik.
- Telefon/narx/tavsifning buyurtmada saqlanishi, narx tasdiqlashdan oldin o‘zgarsa rad etish.
- v1 → v3 migratsiyasida balans, buyurtma, moliyaviy jurnal va manzillarning saqlanishi; takror migratsiya.

Oldingi v2 tekshiruvida Desktopdagi mavjud bazaning alohida nusxasi ham migratsiya qilinib tekshirilgan: qatorlar soni, jami balans va jadvallar o‘rtasidagi bog‘lanishlar saqlangan. Asl baza testlarda o‘zgartirilmaydi.

Testlar haqiqiy Telegramga xabar yubormaydi. Jonli Telegram, Docker build va Railway deploy alohida tekshirilishi kerak.
