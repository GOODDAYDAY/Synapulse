"""Gmail monitoring job — periodically fetch unseen emails via IMAP."""

import asyncio
import logging

from apps.bot.config.settings import config
from apps.bot.job._imap import EmailCronJob, fetch_unseen

logger = logging.getLogger("synapulse.job.gmail")

IMAP_HOST = "imap.gmail.com"


class Job(EmailCronJob):
    name = "gmail_monitor"

    def validate(self) -> None:
        """Check that Gmail secrets are set in .env."""
        missing = []
        if not config.GMAIL_ADDRESS:
            missing.append("GMAIL_ADDRESS")
        if not config.GMAIL_APP_PASSWORD:
            missing.append("GMAIL_APP_PASSWORD")
        if missing:
            raise EnvironmentError(
                f"{', '.join(missing)} required for gmail_monitor job. "
                "Set them in .env"
            )

    async def fetch(self) -> list[dict]:
        return await asyncio.to_thread(
            fetch_unseen, IMAP_HOST, config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD
        )
