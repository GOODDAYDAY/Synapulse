"""Outlook monitoring job — periodically fetch unseen emails via IMAP."""

import asyncio
import logging

from apps.bot.config.settings import config
from apps.bot.job._imap import EmailCronJob, fetch_unseen

logger = logging.getLogger("synapulse.job.outlook")

IMAP_HOST = "outlook.office365.com"


class Job(EmailCronJob):
    name = "outlook_monitor"

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
