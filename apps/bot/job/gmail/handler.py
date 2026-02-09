"""Gmail monitoring job — periodically fetch unseen emails via IMAP."""

import asyncio
import email
import imaplib
import logging
from email.header import decode_header

from apps.bot.config.settings import config
from apps.bot.job.cron import CronJob

logger = logging.getLogger("synapulse.job.gmail")

IMAP_HOST = "imap.gmail.com"


def _decode_header(raw: str) -> str:
    """Decode an email header value to a plain string."""
    parts = decode_header(raw or "")
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return "".join(decoded)


def _extract_text(msg: email.message.Message) -> str:
    """Extract plain-text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return ""


def _fetch_unseen_emails() -> list[dict]:
    """Connect to Gmail IMAP, fetch UNSEEN emails, mark them as SEEN."""
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        conn.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        conn.select("INBOX")

        _, data = conn.search(None, "UNSEEN")
        msg_ids = data[0].split()
        if not msg_ids:
            return []

        results = []
        for mid in msg_ids:
            _, msg_data = conn.fetch(mid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            results.append({
                "from": _decode_header(msg.get("From", "")),
                "subject": _decode_header(msg.get("Subject", "")),
                "date": msg.get("Date", ""),
                "body": _extract_text(msg)[:2000],
            })
        return results
    finally:
        try:
            conn.logout()
        except Exception:
            pass


class Job(CronJob):
    name = "gmail_monitor"
    # Class defaults — overridable via jobs.json
    prompt = (
        "You are an email summarizer. Summarize this email in 2-4 sentences. "
        "Capture the key point and any action items. Be concise."
    )
    schedule = "*/5 * * * *"

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

    async def process(self, item: dict, prompt: str) -> str:
        """Summarize email via AI if prompt is configured, otherwise use raw text."""
        text = self.format_for_ai(item)
        if prompt and self.summarize:
            logger.debug("Summarizing email: %s", item.get("subject", ""))
            summary = await self.summarize(prompt, text)
        else:
            summary = text
        return self.format_notification(item, summary)

    async def fetch(self) -> list[dict]:
        return await asyncio.to_thread(_fetch_unseen_emails)

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
