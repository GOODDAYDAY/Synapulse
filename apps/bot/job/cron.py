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

            # Resolve schedule and prompt:
            # JSON value takes priority; fall back to class default if absent.
            # Re-evaluated every tick, so editing jobs.json takes effect
            # without restarting the bot.
            schedule = cfg.get("schedule", self.schedule)
            prompt = cfg.get("prompt", self.prompt)
            logger.info(
                "Job %s active: schedule=%s, notify_channel=%s, prompt=%s",
                self.name, schedule, notify_channel,
                f"{prompt[:50]}..." if len(prompt) > 50 else (prompt or "<none>"),
            )

            # Compute next cron time and sleep until then
            cron = croniter(schedule, datetime.now(timezone.utc))
            next_time = cron.get_next(datetime)
            delay = (next_time - datetime.now(timezone.utc)).total_seconds()
            logger.info("Job %s next tick at %s (%.0fs)", self.name, next_time, delay)
            if delay > 0:
                await asyncio.sleep(delay)

            # Fetch items
            logger.info("Job %s fetching...", self.name)
            try:
                items = await self.fetch()
            except Exception:
                logger.exception("Job %s fetch failed", self.name)
                continue

            if not items:
                logger.info("Job %s fetched 0 items, nothing to do", self.name)
                continue

            # Process and notify
            logger.info("Job %s fetched %d item(s), processing", self.name, len(items))
            try:
                for i, item in enumerate(items, 1):
                    message = await self.process(item, prompt)
                    await notify(notify_channel, message)
                    logger.info("Job %s notified item %d/%d", self.name, i, len(items))
            except Exception:
                logger.exception("Job %s processing failed", self.name)
