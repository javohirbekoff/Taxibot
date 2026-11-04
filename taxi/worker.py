import asyncio
import json
import logging
import time
from collections import defaultdict

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from .db import order_text
from .keyboards import buttons, main_menu

log = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.global_next = 0.0
        self.chat_next = defaultdict(float)

    async def wait(self, chat):
        async with self.lock:
            now = time.monotonic()
            scheduled = max(now, self.global_next, self.chat_next[chat])
            self.global_next = scheduled + 0.06  # below 20 API operations/second
            self.chat_next[chat] = scheduled + 1.05
            if len(self.chat_next) > 10000:
                self.chat_next = defaultdict(float, {k: v for k, v in self.chat_next.items() if v > now})
        await asyncio.sleep(max(0, scheduled - time.monotonic()))


class OutboxWorker:
    def __init__(self, bot, db, config):
        self.bot, self.db, self.config = bot, db, config
        self.limiter = RateLimiter()
        self.stop = asyncio.Event()

    async def deliver(self, job):
        p = json.loads(job['payload'])
        chat, kind = job['chat_id'], job['kind']
        await self.limiter.wait(chat)
        markup = buttons(p['buttons']) if p.get('buttons') else None
        if p.get('driver_menu'):
            markup = main_menu('driver', True)
        if kind == 'send':
            await self.bot.send_message(chat, p['text'], reply_markup=markup)
        elif kind == 'photo':
            await self.bot.send_photo(chat, p['photo'], caption=p['text'], reply_markup=markup)
        elif kind == 'invite':
            d = await self.db.driver(chat)
            if d and d['status'] == 'approved':
                await self.limiter.wait(self.config.driver_channel)
                invite = await self.bot.create_chat_invite_link(
                    self.config.driver_channel, name=d['driver_id'],
                    creates_join_request=True, expire_date=int(time.time()) + 86400)
                await self.limiter.wait(chat)
                await self.bot.send_message(chat, 'Haydovchilar kanaliga kirish (24 soat):\n' + invite.invite_link)
        elif kind == 'order_card':
            rows = await self.db.fetch('SELECT * FROM orders WHERE order_id=?', (p['order_id'],))
            d = await self.db.driver(chat)
            if not rows or rows[0]['status'] != 'active' or not d or d['status'] != 'approved':
                return
            o = rows[0]
            message = await self.bot.send_message(chat, order_text(o),
                                                  reply_markup=buttons([[('🚖 Zakazni olish', f"take:{o['order_id']}")]]))
            await self.db.record_card(o['order_id'], chat, message.message_id)
        elif kind == 'close_card':
            rows = await self.db.fetch('SELECT status FROM orders WHERE order_id=?', (p['order_id'],))
            label = '❌ Zakaz olindi' if rows and rows[0]['status'] == 'taken' else '❌ Bekor qilindi'
            await self.bot.edit_message_reply_markup(chat_id=chat, message_id=p['message_id'],
                                                     reply_markup=buttons([[(label, 'closed')]]))
        else:
            raise ValueError('Unknown outbox kind')

    async def process(self, job):
        try:
            await self.deliver(job)
        except TelegramRetryAfter as e:
            await self.db.job_result(job['id'], 'pending', e.retry_after + 1, 'TelegramRetryAfter')
        except TelegramForbiddenError:
            await self.db.job_result(job['id'], 'dead', error='TelegramForbiddenError')
        except TelegramBadRequest as e:
            # Repeated markup edit after a crash is already complete.
            if job['kind'] == 'close_card' and 'message is not modified' in str(e).lower():
                await self.db.job_result(job['id'], 'done')
            else:
                await self.db.job_result(job['id'], 'dead', error='TelegramBadRequest')
                log.warning('Outbox job %s needs admin review: TelegramBadRequest', job['id'])
        except Exception as e:
            status = 'dead' if job['attempts'] >= 15 else 'pending'
            await self.db.job_result(job['id'], status, min(600, 2 ** min(job['attempts'], 9)), type(e).__name__)
            log.warning('Outbox job %s: %s (%s)', job['id'], type(e).__name__, status)
        else:
            await self.db.job_result(job['id'], 'done')

    async def run(self):
        while not self.stop.is_set():
            jobs = await self.db.next_jobs()
            if jobs:
                await asyncio.gather(*(self.process(j) for j in jobs))
            else:
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=0.5)
                except TimeoutError:
                    pass
