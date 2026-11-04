import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from taxi.db import Database, UserError


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'test.sqlite3', admins=(999,))
        await self.db.init()
        await self.db.add_route('Shirin ➡️ Bekobod')
        self.rid = (await self.db.fetch('SELECT id FROM routes'))[0]['id']
        await self.db.register(1, dict(name='Passenger', phone='+998901234567'), 'passenger')

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def driver(self, uid, balance=10000):
        await self.db.register(uid, dict(name=f'Driver {uid}', phone='+998901234568',
                                        year=1990, car='Gentra 2023', plate='20 A 777 AA', photo='photo'), 'driver')
        d = await self.db.driver(uid)
        did = await self.db.moderate(999, d['id'], d['revision'], True)
        if balance:
            await self.db.topup(999, did, balance, f'topup:{uid}')
        return did

    async def order(self, seats=2, uid=1, key='test-order'):
        return await self.db.create_order(uid, self.rid, seats, 'Hujjatlar' if seats == 0 else None, key)

    async def test_wal_and_foreign_keys(self):
        self.assertEqual((await self.db.fetch('PRAGMA journal_mode'))[0]['journal_mode'], 'wal')
        with self.assertRaises(sqlite3.IntegrityError):
            await self.db.run(lambda c: c.execute('INSERT INTO order_messages VALUES(9999,1,1)'))

    async def test_one_winner_under_30_simultaneous_claims(self):
        drivers = [await self.driver(i) for i in range(100, 110)]
        oid = await self.order()
        # Separate Database objects and connections, not a process-local asyncio lock.
        instances = [Database(self.db.path) for _ in range(30)]
        results = await asyncio.gather(*(instances[i].claim(100 + i % 10, oid) for i in range(30)), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(sum(isinstance(r, UserError) for r in results), 29)
        balances = await self.db.fetch('SELECT SUM(balance) AS total FROM drivers')
        self.assertEqual(balances[0]['total'], 100000 - 1000)
        self.assertEqual(len(await self.db.fetch("SELECT * FROM ledger WHERE kind='commission'")), 1)
        self.assertEqual(len(await self.db.fetch("SELECT * FROM outbox WHERE dedup_key LIKE 'claimed:%'")), 3)

    async def test_two_orders_cannot_overdraw_same_driver(self):
        await self.driver(100, balance=1000)
        await self.db.register(2, dict(name='Other', phone='+998901234569'), 'passenger')
        a, b = await self.order(key='a'), await self.order(uid=2, key='b')
        results = await asyncio.gather(self.db.claim(100, a), self.db.claim(100, b), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual((await self.db.driver(100))['balance'], 0)
        self.assertEqual(len(await self.db.fetch("SELECT * FROM orders WHERE status='active'")), 1)

    async def test_failure_rolls_back_debit_and_order(self):
        await self.driver(100)
        oid = await self.order()
        await self.db.run(lambda c: c.execute("CREATE TRIGGER fail_ledger BEFORE INSERT ON ledger "
                                              "WHEN NEW.kind='commission' BEGIN SELECT RAISE(ABORT,'injected'); END"))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.db.claim(100, oid)
        self.assertEqual((await self.db.driver(100))['balance'], 10000)
        self.assertEqual((await self.db.fetch('SELECT status FROM orders'))[0]['status'], 'active')
        self.assertFalse(await self.db.fetch("SELECT * FROM outbox WHERE dedup_key LIKE 'claimed:%'"))

    async def test_post_free_and_insufficient_balance(self):
        await self.driver(100, balance=0)
        oid = await self.order(1)
        with self.assertRaises(UserError):
            await self.db.claim(100, oid)
        await self.db.cancel_order(1, oid)
        post = await self.order(0, key='post')
        await self.db.claim(100, post)
        self.assertEqual((await self.db.driver(100))['balance'], 0)

    async def test_duplicate_topup_exactly_once(self):
        did = await self.driver(100, balance=0)
        results = await asyncio.gather(*(self.db.topup(999, did, 50000, 'same-message') for _ in range(20)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual((await self.db.driver(100))['balance'], 50000)
        with self.assertRaises(UserError):
            await self.db.topup(1, did, 500, 'unauthorized')

    async def test_duplicate_confirmation_and_active_limit(self):
        ids = await asyncio.gather(*(self.order() for _ in range(10)))
        self.assertEqual(len(set(ids)), 1)
        with self.assertRaises(UserError):
            await self.order(key='different')

    async def test_commission_snapshotted_and_route_soft_deleted(self):
        await self.driver(100)
        oid = await self.order()
        await self.db.set_commission(999)
        await self.db.remove_route(self.rid)
        await self.db.claim(100, oid)
        self.assertEqual((await self.db.driver(100))['balance'], 9000)
        with self.assertRaises(UserError):
            await self.order(key='disabled-route')

    async def test_late_broadcast_card_gets_closed(self):
        await self.driver(100)
        oid = await self.order()
        await self.db.claim(100, oid)
        await self.db.record_card(oid, 101, 77)
        rows = await self.db.fetch("SELECT * FROM outbox WHERE kind='close_card'")
        self.assertEqual(len(rows), 1)
        await self.db.record_card(oid, 101, 77)
        self.assertEqual(len(await self.db.fetch("SELECT * FROM outbox WHERE kind='close_card'")), 1)

    async def test_rejected_driver_old_moderation_button_invalid(self):
        data = dict(name='Driver', phone='+998901234568', year=1990, car='Gentra', plate='20 A 777 AA', photo='photo')
        await self.db.register(100, data, 'driver')
        d = await self.db.driver(100)
        await self.db.moderate(999, d['id'], 1, False)
        await self.db.register(100, data, 'driver')
        with self.assertRaises(UserError):
            await self.db.moderate(999, d['id'], 1, True)
        did = await self.db.moderate(999, d['id'], 2, True)
        self.assertEqual(did, '100')

    async def test_cancel_ownership_and_claim_race(self):
        await self.driver(100)
        oid = await self.order()
        with self.assertRaises(UserError):
            await self.db.cancel_order(2, oid)
        results = await asyncio.gather(self.db.cancel_order(1, oid), self.db.claim(100, oid), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, UserError) for r in results), 1)
        o = (await self.db.fetch('SELECT * FROM orders'))[0]
        self.assertEqual((await self.db.driver(100))['balance'], 9000 if o['status'] == 'taken' else 10000)

    async def test_broadcast_has_no_passenger_contact_and_all_approved(self):
        await self.driver(100, balance=1000)
        await self.driver(101, balance=0)
        oid = await self.order()
        jobs = await self.db.fetch("SELECT * FROM outbox WHERE kind='order_card'")
        self.assertEqual([j['chat_id'] for j in jobs], [100, 101])
        self.assertNotIn('+998', jobs[0]['payload'])

    async def test_campaign_confirmation_deduplicated_and_authorized(self):
        await self.driver(100)
        token = await self.db.campaign_draft(999, 'all', 'Salom')
        with self.assertRaises(UserError):
            await self.db.campaign_send(1, token)
        self.assertEqual(await self.db.campaign_send(999, token), 2)
        with self.assertRaises(UserError):
            await self.db.campaign_send(999, token)
        self.assertEqual(len(await self.db.fetch("SELECT * FROM outbox WHERE dedup_key LIKE 'campaign:%'")), 2)

    async def test_outbox_restart_recovery(self):
        await self.order()
        jobs = await self.db.next_jobs()
        self.assertTrue(jobs)
        await self.db.init()
        recovered = await self.db.next_jobs()
        self.assertEqual([r['id'] for r in jobs], [r['id'] for r in recovered])

    async def test_stats(self):
        await self.db.visit(1)
        await self.order()
        s = await self.db.stats('Asia/Tashkent')
        self.assertEqual(s['visitors'], 1)
        self.assertEqual(s['registered'], 1)
        self.assertEqual(s['today_orders'], 1)
        self.assertEqual(s['passengers'], 1)

    async def test_admin_debit_atomic_and_not_commission(self):
        did = await self.driver(100, balance=50000)
        results = await asyncio.gather(*(self.db.debit(999, did, 10000, 'same-debit') for _ in range(10)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual((await self.db.driver(100))['balance'], 40000)
        self.assertEqual((await self.db.stats('Asia/Tashkent'))['revenue'], 0)
        with self.assertRaises(UserError):
            await self.db.debit(999, did, 40001, 'too-much')
        with self.assertRaises(UserError):
            await self.db.debit(1, did, 1, 'unauthorized')
        self.assertEqual((await self.db.driver(100))['balance'], 40000)

    async def test_debit_and_claim_cannot_overdraw(self):
        did = await self.driver(100, balance=1000)
        oid = await self.order()
        results = await asyncio.gather(self.db.claim(100, oid), self.db.debit(999, did, 1000, 'debit-race'), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, UserError) for r in results), 1)
        self.assertEqual((await self.db.driver(100))['balance'], 0)

    async def test_route_fare_and_phone_snapshots(self):
        await self.db.save_route(self.rid, 'Shirin ➡️ Bekobod', 40000, 'Odam boshiga')
        oid = await self.db.create_order(1, self.rid, 2, None, 'snapshot', phone='+998991111111', note='Markaz',
                                         expected_route=['Shirin ➡️ Bekobod', 40000, 'Odam boshiga'])
        await self.db.save_route(self.rid, 'Yangi nom', 50000, 'Yangi tavsif')
        await self.db.run(lambda c: c.execute("UPDATE users SET phone='+998992222222' WHERE telegram_id=1").rowcount)
        await self.driver(100)
        await self.db.claim(100, oid)
        o = (await self.db.fetch('SELECT * FROM orders'))[0]
        self.assertEqual((o['fare'], o['route_description'], o['contact_phone']), (40000, 'Odam boshiga', '+998991111111'))
        jobs = await self.db.fetch("SELECT payload FROM outbox WHERE dedup_key LIKE 'claimed:%:driver'")
        self.assertIn('+998991111111', jobs[0]['payload'])
        self.assertNotIn('+998992222222', jobs[0]['payload'])

    async def test_price_changed_before_confirmation_requires_restart(self):
        await self.db.save_route(self.rid, 'Shirin ➡️ Bekobod', 50000, 'Yangi')
        with self.assertRaises(UserError):
            await self.db.create_order(1, self.rid, 1, None, 'changed', phone='+998901234567',
                                       expected_route=['Shirin ➡️ Bekobod', 40000, 'Eski'])
        self.assertFalse(await self.db.fetch('SELECT * FROM orders'))

    async def test_v1_migration_preserves_balance_orders_and_ledger(self):
        path = Path(self.tmp.name) / 'old.sqlite3'
        c = sqlite3.connect(path)
        c.executescript((Path(__file__).parent / 'fixtures/schema_v1.sql').read_text(encoding='utf-8'))
        c.execute("INSERT INTO users VALUES(1,'Passenger','+998901234567','passenger',0)")
        c.execute("INSERT INTO users VALUES(100,'Driver','+998901234568','driver',0)")
        c.execute("INSERT INTO drivers(driver_id,telegram_id,birth_year,car_model,car_number,photo_file_id,balance,status) VALUES('DRV-1001',100,1990,'Car','Plate','photo',4500,'approved')")
        c.execute("INSERT INTO routes(route_name) VALUES('A to B')")
        c.execute("INSERT INTO orders(request_key,passenger_id,route_id,route,seats,commission,status,driver_id,created_at) VALUES('old',1,1,'A to B',1,500,'taken','DRV-1001',0)")
        c.execute("INSERT INTO ledger(driver_id,amount,kind,idempotency_key,actor,created_at) VALUES('DRV-1001',-500,'commission','old',100,0)")
        c.execute("INSERT INTO campaigns VALUES('draft',999,'DRV-1001','Salom','draft',0)")
        c.commit()
        c.close()
        migrated = Database(path, (999,))
        await migrated.init()
        self.assertTrue(Path(str(path) + '.v1-backup').exists())
        self.assertEqual((await migrated.driver(100))['balance'], 4500)
        self.assertEqual((await migrated.driver(100))['driver_id'], '100')
        self.assertEqual((await migrated.fetch('SELECT driver_id FROM orders'))[0]['driver_id'], '100')
        self.assertEqual((await migrated.fetch('SELECT driver_id FROM ledger'))[0]['driver_id'], '100')
        self.assertEqual((await migrated.fetch('SELECT target FROM campaigns'))[0]['target'], '100')
        self.assertFalse(await migrated.fetch('PRAGMA foreign_key_check'))
        await migrated.init()
        self.assertEqual((await migrated.driver(100))['balance'], 4500)


if __name__ == '__main__':
    unittest.main()
