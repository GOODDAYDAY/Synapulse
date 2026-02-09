"""Shared IMAP utilities for email monitoring jobs."""

import email
import email.message
import imaplib
import logging
from datetime import datetime, timedelta, timezone
from email.header import decode_header

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


def fetch_unseen(host: str, address: str, password: str) -> list[dict]:
    """Connect to an IMAP server, fetch recent UNSEEN emails, mark them as SEEN.

    Combines UNSEEN + SINCE (2 days ago) so the first run doesn't pull
    the entire mailbox history. IMAP fetch marks emails as SEEN, so
    subsequent runs only return new arrivals.
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
