import asyncio
import contextlib
import logging
import sys

import portalocker
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand

from taxi.config import Config
from taxi.db import Database
from taxi.handlers import make_router
from taxi.storage import SQLiteStorage
from taxi.worker import OutboxWorker


async def main(config):
    db = Database(config.db_path, config.admins, config.driver_channel, config.orders_channel, config.commission)
    await db.init()
    bot = Bot(config.token)  # Plain text: user input is never parsed as HTML/Markdown.
    dp = Dispatcher(storage=SQLiteStorage(db), events_isolation=SimpleEventIsolation())
    dp.include_router(make_router(db, config))
    worker = OutboxWorker(bot, db, config)
    worker_task = None
    poll_task = None
    try:
        await bot.get_me()
        await bot.set_my_commands([BotCommand(command='start', description='Bosh menyu')])
        webhook = await bot.get_webhook_info()
        if webhook.url:
            raise RuntimeError('Webhook is configured. Remove it before starting polling; updates are not dropped automatically.')
        worker_task = asyncio.create_task(worker.run(), name='outbox')
        # Sequential ingress keeps FSM order and completes each update before the next poll.
        # Database atomicity also holds across separate connections/processes (tested).
        poll_task = asyncio.create_task(dp.start_polling(bot, handle_as_tasks=False, close_bot_session=False), name='polling')
        done, _ = await asyncio.wait([worker_task, poll_task], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()  # A worker crash must fail the process so Railway restarts it.
    finally:
        worker.stop.set()
        if poll_task and not poll_task.done():
            with contextlib.suppress(RuntimeError):
                await dp.stop_polling()
            await asyncio.gather(poll_task, return_exceptions=True)
        try:
            if worker_task:
                try:
                    await asyncio.wait_for(worker_task, timeout=20)
                except (TimeoutError, asyncio.CancelledError):
                    worker_task.cancel()
                    await asyncio.gather(worker_task, return_exceptions=True)
        finally:
            await dp.fsm.close()
            await bot.session.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    # aiogram network errors can include request details; keep library logging quiet.
    logging.getLogger('aiogram').setLevel(logging.CRITICAL)
    try:
        cfg = Config.load()
        # OS lock is automatically released on crash, unlike a stale PID file.
        with portalocker.Lock(cfg.db_path + '.lock', mode='a', timeout=0):
            asyncio.run(main(cfg))
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as exc:
        logging.error('Bot stopped: %s. Check configuration, database volume and connectivity.', type(exc).__name__)
        sys.exit(1)
