PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
 telegram_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, phone TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('passenger','driver','admin')),
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS visitors (telegram_id INTEGER PRIMARY KEY, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS drivers (
 id INTEGER PRIMARY KEY AUTOINCREMENT, driver_id TEXT UNIQUE,
 telegram_id INTEGER NOT NULL UNIQUE REFERENCES users(telegram_id),
 birth_year INTEGER NOT NULL, car_model TEXT NOT NULL, car_number TEXT NOT NULL,
 photo_file_id TEXT NOT NULL, balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS routes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, route_name TEXT NOT NULL UNIQUE,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
 order_id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_key TEXT NOT NULL UNIQUE, passenger_id INTEGER NOT NULL REFERENCES users(telegram_id),
 route_id INTEGER NOT NULL REFERENCES routes(id), route TEXT NOT NULL,
 seats INTEGER NOT NULL CHECK(seats BETWEEN 0 AND 6), mail_desc TEXT,
 commission INTEGER NOT NULL CHECK(commission>=0),
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','taken','cancelled')),
 driver_id TEXT REFERENCES drivers(driver_id), created_at INTEGER NOT NULL, taken_at INTEGER,
 CHECK((seats=0 AND mail_desc IS NOT NULL) OR seats>0)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_order ON orders(passenger_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS orders_driver ON orders(driver_id);
CREATE INDEX IF NOT EXISTS orders_created ON orders(created_at);
CREATE TABLE IF NOT EXISTS ledger (
 id INTEGER PRIMARY KEY AUTOINCREMENT, driver_id TEXT NOT NULL REFERENCES drivers(driver_id),
 amount INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('topup','commission','debit')),
 idempotency_key TEXT NOT NULL UNIQUE, actor INTEGER NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 key TEXT PRIMARY KEY, state TEXT, data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY AUTOINCREMENT, dedup_key TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL, chat_id INTEGER NOT NULL, payload TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','done','dead')),
 attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
 last_error TEXT, created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(status,available_at,id);
CREATE TABLE IF NOT EXISTS order_messages (
 order_id INTEGER NOT NULL REFERENCES orders(order_id), chat_id INTEGER NOT NULL,
 message_id INTEGER NOT NULL, PRIMARY KEY(order_id,chat_id,message_id)
);
CREATE TABLE IF NOT EXISTS campaigns (
 token TEXT PRIMARY KEY, admin_id INTEGER NOT NULL, target TEXT NOT NULL,
 text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', created_at INTEGER NOT NULL
);
