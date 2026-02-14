"""QQ Mail monitoring job — periodically fetch unseen emails via IMAP.

QQ Mail IMAP works from overseas servers. Requires an app password (授权码)
generated from QQ Mail settings: Settings → Account → POP3/IMAP/SMTP → Generate.
"""

import asyncio
import logging

from apps.bot.config.settings import config
from apps.bot.job._imap import EmailCronJob, fetch_unseen

logger = logging.getLogger("synapulse.job.qqmail")

IMAP_HOST = "imap.qq.com"


class Job(EmailCronJob):
    name = "qqmail_monitor"

    def validate(self) -> None:
        """Check that QQ Mail secrets are set in .env."""
        missing = []
        if not config.QQ_MAIL_ADDRESS:
            missing.append("QQ_MAIL_ADDRESS")
        if not config.QQ_MAIL_APP_PASSWORD:
            missing.append("QQ_MAIL_APP_PASSWORD")
        if missing:
            raise EnvironmentError(
                f"{', '.join(missing)} required for qqmail_monitor job. "
                "Set them in .env (app password from QQ Mail settings)"
            )

    async def fetch(self) -> list[dict]:
        return await asyncio.to_thread(
            fetch_unseen, IMAP_HOST, config.QQ_MAIL_ADDRESS, config.QQ_MAIL_APP_PASSWORD
        )
