"""Base class for continuous listener jobs."""

import asyncio
import logging
from abc import abstractmethod
from collections.abc import AsyncIterator

from apps.bot.config.jobs import load_job_config
from apps.bot.job.base import BaseJob, NotifyCallback

logger = logging.getLogger("synapulse.job.listen")


class ListenJob(BaseJob):
    """Job that listens for events continuously."""

    @abstractmethod
    async def listen(self) -> AsyncIterator[dict]:
        """Yield items as they arrive."""

    async def start(self, notify: NotifyCallback) -> None:
        logger.info("Job %s loop started", self.name)
        while True:
            # Hot reload: re-read config before entering listener
            cfg = load_job_config(self.name)

            # Guard: disabled → sleep and recheck
            if not cfg.get("enabled", False):
                logger.debug("Job %s disabled, rechecking in 60s", self.name)
                await asyncio.sleep(60)
                continue

            # Guard: secrets not ready → sleep and retry
            try:
                self.validate()
            except Exception as e:
                logger.warning("Job %s validation failed: %s", self.name, e)
                await asyncio.sleep(60)
                continue

            # Guard: no notify channel → can't send anywhere
            notify_channel = cfg.get("notify_channel", "")
            if not notify_channel:
                logger.warning("Job %s has no notify_channel configured", self.name)
                await asyncio.sleep(60)
                continue

            prompt = cfg.get("prompt", self.prompt)
            logger.info("Job %s entering listener", self.name)

            # Inner loop: process items as they arrive, re-read config per item
            async for item in self.listen():
                cfg = load_job_config(self.name)
                if not cfg.get("enabled", False):
                    logger.info("Job %s disabled mid-stream, breaking", self.name)
                    break
                notify_channel = cfg.get("notify_channel", "")
                prompt = cfg.get("prompt", self.prompt)
                try:
                    message = await self.process(item, prompt)
                    await notify(notify_channel, message)
                except Exception:
                    logger.exception("Job %s failed on item", self.name)
