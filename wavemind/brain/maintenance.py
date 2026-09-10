"""Trusted server-owned serial draining; domain callers retain explicit control."""

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


class BrainMaintenance:
    def __init__(self, service):
        self.service = service
        self._stop = asyncio.Event()
        self._task = None
        self._failed = False

    async def _batch(self):
        try:
            await run_in_threadpool(self.service.drain_outbox, limit=100)
            self._failed = False
        except Exception:
            if not self._failed:
                logger.warning("Brain maintenance remains pending; retry scheduled.")
            self._failed = True

    async def start(self):
        await self._batch()
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1)
            except asyncio.TimeoutError:
                if not self._stop.is_set():
                    await self._batch()

    async def stop(self):
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.shield(self._task)
            except asyncio.CancelledError:
                # Complete the owned drain before a surrounding server closes SQLite.
                await self._task
                raise
