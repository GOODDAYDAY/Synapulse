"""Outlook monitoring job — periodically fetch unseen emails via IMAP."""

import asyncio
import logging

from apps.bot.config.settings import config
from apps.bot.job._imap import fetch_unseen
from apps.bot.job.cron import CronJob

logger = logging.getLogger("synapulse.job.outlook")

IMAP_HOST = "outlook.office365.com"


class Job(CronJob):
    name = "outlook_monitor"
    # Class defaults — overridable via jobs.json
    prompt = (
        "You are an email summarizer. Summarize this email in 2-4 sentences. "
        "Capture the key point and any action items. Be concise."
    )
    schedule = "*/5 * * * *"

    def validate(self) -> None:
        """Check that Outlook secrets are set in .env."""
        missing = []
        if not config.OUTLOOK_ADDRESS:
            missing.append("OUTLOOK_ADDRESS")
        if not config.OUTLOOK_APP_PASSWORD:
            missing.append("OUTLOOK_APP_PASSWORD")
        if missing:
            raise EnvironmentError(
                f"{', '.join(missing)} required for outlook_monitor job. "
                "Set them in .env"
            )

    async def fetch(self) -> list[dict]:
        return await asyncio.to_thread(
            fetch_unseen, IMAP_HOST, config.OUTLOOK_ADDRESS, config.OUTLOOK_APP_PASSWORD
        )

    async def process(self, item: dict, prompt: str) -> str:
        """Summarize email via AI if prompt is configured, otherwise use raw text."""
        text = self.format_for_ai(item)
        if prompt and self.summarize:
            logger.debug("Summarizing email: %s", item.get("subject", ""))
            summary = await self.summarize(prompt, text)
        else:
            summary = text
        return self.format_notification(item, summary)

    def format_for_ai(self, item: dict) -> str:
        return (
            f"From: {item['from']}\n"
            f"Subject: {item['subject']}\n"
            f"Date: {item['date']}\n"
            f"Body:\n{item['body']}"
        )

    def format_notification(self, item: dict, summary: str) -> str:
        return (
            f"**New Email**\n"
            f"> **From:** {item['from']}\n"
            f"> **Subject:** {item['subject']}\n"
            f"> **Date:** {item['date']}\n"
            f"\n"
            f"**Summary:**\n"
            f"{summary}"
        )
