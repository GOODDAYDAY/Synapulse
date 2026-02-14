"""Shared IMAP utilities and base class for email monitoring jobs."""

import email
import email.message
import imaplib
import logging
from datetime import datetime, timedelta, timezone
from email.header import decode_header

from apps.bot.job.cron import CronJob

logger = logging.getLogger("synapulse.job.imap")


def decode_header_value(raw: str) -> str:
    """Decode an email header value to a plain string."""
    parts = decode_header(raw or "")
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return "".join(decoded)


def extract_text(msg: email.message.Message) -> str:
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


MAX_FETCH = 20


def fetch_unseen(host: str, address: str, password: str) -> list[dict]:
    """Connect to an IMAP server, fetch recent UNSEEN emails, mark them as SEEN.

    Combines UNSEEN + SINCE (2 days ago) so the first run doesn't pull
    the entire mailbox history. IMAP fetch marks emails as SEEN, so
    subsequent runs only return new arrivals.

    Some providers (notably QQ Mail) don't sync web/app read status with the
    IMAP \\Seen flag, and may ignore the SINCE filter. MAX_FETCH caps the
    number of emails fetched per run to protect against mailbox explosions.
    Only the most recent emails are fetched (highest IMAP sequence numbers).
    """
    since_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%d-%b-%Y")
    logger.info("Connecting to %s as %s", host, address)
    conn = imaplib.IMAP4_SSL(host)
    try:
        conn.login(address, password)
        conn.select("INBOX")
        logger.info("IMAP login successful, searching UNSEEN SINCE %s", since_date)

        _, data = conn.search(None, f"(UNSEEN SINCE {since_date})")
        msg_ids = data[0].split()
        if not msg_ids:
            logger.info("No unseen emails found")
            return []

        # Cap to most recent emails (highest sequence numbers = newest).
        if len(msg_ids) > MAX_FETCH:
            logger.warning(
                "Found %d unseen emails, capping to newest %d",
                len(msg_ids), MAX_FETCH,
            )
            msg_ids = msg_ids[-MAX_FETCH:]
        else:
            logger.info("Found %d unseen email(s), fetching", len(msg_ids))

        results = []
        for mid in msg_ids:
            _, msg_data = conn.fetch(mid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = decode_header_value(msg.get("Subject", ""))
            sender = decode_header_value(msg.get("From", ""))
            logger.info("  Email: from=%s, subject=%s", sender, subject)

            results.append({
                "from": sender,
                "subject": subject,
                "date": msg.get("Date", ""),
                "body": extract_text(msg)[:2000],
            })
        return results
    finally:
        try:
            conn.logout()
            logger.info("IMAP connection closed")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Shared base class for all IMAP-based email monitoring jobs.
# Each concrete job only needs: name, validate(), fetch().
# ---------------------------------------------------------------------------

_MAX_HISTORY = 500

_EMAIL_PROMPT = (
    "You are an email classifier and summarizer.\n"
    "Analyze the email and respond in EXACTLY this format:\n"
    "\n"
    "Priority: [High / Medium / Low]\n"
    "Tags: [comma-separated from: work, personal, finance, notification, social, newsletter, ad]\n"
    "Summary: [2-4 sentences. MUST keep concrete data: amounts, dates/times, names, "
    "recipients, deadlines, account numbers. Never replace specific numbers or names "
    "with vague descriptions. Include any required action.]\n"
    "\n"
    "If this email is clearly a mass advertisement, bulk marketing, automated promotion, "
    "or spam with no personal relevance, respond with ONLY the word: SKIP"
)


class EmailCronJob(CronJob):
    """Shared behavior for IMAP-based email monitoring jobs.

    Subclasses only need to define name, validate(), and fetch().
    Classification, ad filtering, deduplication, and notification formatting
    are handled here.
    """

    prompt = _EMAIL_PROMPT
    schedule = "*/5 * * * *"

    def __init__(self) -> None:
        self._sent_history: list[str] = []

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def _email_key(item: dict) -> str:
        """Build a dedup key from sender + subject + date."""
        return f"{item.get('from', '')}|{item.get('subject', '')}|{item.get('date', '')}"

    def _is_duplicate(self, key: str) -> bool:
        """Return True if this email was already sent."""
        return key in self._sent_history

    def _record(self, key: str) -> None:
        """Add key to history, trimming oldest entries beyond the cap."""
        self._sent_history.append(key)
        if len(self._sent_history) > _MAX_HISTORY:
            self._sent_history = self._sent_history[-_MAX_HISTORY:]

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    async def process(self, item: dict, prompt: str) -> str:
        """Classify and summarize email; return empty string to skip ads/duplicates."""
        key = self._email_key(item)
        if self._is_duplicate(key):
            logger.debug("Duplicate email skipped: %s", item.get("subject", ""))
            return ""

        text = self.format_for_ai(item)
        if prompt and self.summarize:
            logger.debug("Classifying email: %s", item.get("subject", ""))
            result = await self.summarize(prompt, text)
            if result.strip().upper() == "SKIP":
                logger.info("Filtered ad/spam: %s", item.get("subject", ""))
                self._record(key)
                return ""
            summary = result
        else:
            summary = text

        self._record(key)
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
            f"{summary}"
        )
