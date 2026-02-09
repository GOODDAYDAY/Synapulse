"""Base class for scheduled (cron-style) jobs."""

import asyncio
import logging
from abc import abstractmethod
from datetime import datetime, timezone

from croniter import croniter

from apps.bot.config.jobs import load_job_config
from apps.bot.job.base import BaseJob, NotifyCallback

logger = logging.getLogger("synapulse.job.cron")


class CronJob(BaseJob):
    """Job that runs on a cron schedule."""

    schedule: str  # cron expression, e.g. "*/5 * * * *"

    @abstractmethod
    async def fetch(self) -> list[dict]:
        """Fetch new items to process."""

    async def start(self, notify: NotifyCallback) -> None:
        logger.info("Job %s loop started", self.name)
        while True:
            # Hot reload: re-read config every tick
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

            # Resolve schedule and prompt (JSON overrides class defaults)
            schedule = cfg.get("schedule", self.schedule)
            prompt = cfg.get("prompt", self.prompt)

            # Compute next cron time and sleep until then
            cron = croniter(schedule, datetime.now(timezone.utc))
            next_time = cron.get_next(datetime)
            delay = (next_time - datetime.now(timezone.utc)).total_seconds()
            if delay > 0:
                logger.debug("Job %s sleeping %.0fs until next tick", self.name, delay)
                await asyncio.sleep(delay)

            # Fetch and process items
            try:
                items = await self.fetch()
                if items:
                    logger.info("Job %s fetched %d item(s)", self.name, len(items))
                for item in items:
                    message = await self.process(item, prompt)
                    await notify(notify_channel, message)
            except Exception:
                logger.exception("Job %s tick failed", self.name)
