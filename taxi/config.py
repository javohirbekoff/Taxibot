import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    admins: tuple[int, ...]
    driver_channel: int
    orders_channel: int
    db_path: str
    timezone: str
    commission: int

    @classmethod
    def load(cls):
        load_dotenv()
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token or token.startswith("replace_"):
            raise ValueError("BOT_TOKEN ni .env yoki Railway Variables da kiriting")
        admins = tuple(int(x.strip()) for x in os.environ["ADMIN_IDS"].split(",") if x.strip())
        if not admins or any(x <= 0 for x in admins):
            raise ValueError("ADMIN_IDS musbat Telegram ID lardan iborat bo'lishi kerak")
        channels = [int(os.environ[k]) for k in ("DRIVER_CHANNEL_ID", "ORDERS_CHANNEL_ID")]
        if any(x >= 0 for x in channels) or channels[0] == channels[1]:
            raise ValueError("Ikkita alohida maxfiy kanalning manfiy ID sini kiriting")
        timezone = os.getenv("TIMEZONE", "Asia/Tashkent")
        ZoneInfo(timezone)
        commission = int(os.getenv("DEFAULT_COMMISSION", "500"))
        if not 0 <= commission <= 1_000_000_000:
            raise ValueError("DEFAULT_COMMISSION noto'g'ri")
        path = os.getenv("DB_PATH", "data/bot.sqlite3")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return cls(token, admins, *channels, path, timezone, commission)
