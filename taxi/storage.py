import json

from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, StorageKey


class SQLiteStorage(BaseStorage):
    """FSM survives restarts; SimpleEventIsolation serializes each user's updates."""
    def __init__(self, db):
        self.db = db
        self.builder = DefaultKeyBuilder(with_bot_id=True, with_destiny=True)

    def key(self, key: StorageKey):
        return self.builder.build(key)

    async def set_state(self, key, state=None):
        value = state.state if hasattr(state, 'state') else state
        await self.db.run(lambda c: c.execute('INSERT INTO sessions(key,state) VALUES(?,?) '
                                              'ON CONFLICT(key) DO UPDATE SET state=excluded.state',
                                              (self.key(key), value)).rowcount)

    async def get_state(self, key):
        rows = await self.db.fetch('SELECT state FROM sessions WHERE key=?', (self.key(key),))
        return rows[0]['state'] if rows else None

    async def set_data(self, key, data):
        await self.db.run(lambda c: c.execute('INSERT INTO sessions(key,data) VALUES(?,?) '
                                              'ON CONFLICT(key) DO UPDATE SET data=excluded.data',
                                              (self.key(key), json.dumps(data, ensure_ascii=False))).rowcount)

    async def get_data(self, key):
        rows = await self.db.fetch('SELECT data FROM sessions WHERE key=?', (self.key(key),))
        return json.loads(rows[0]['data']) if rows else {}

    async def close(self):
        pass
