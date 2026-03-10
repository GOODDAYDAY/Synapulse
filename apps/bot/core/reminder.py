"""Background reminder checker — polls for due reminders and fires them.

Runs as an asyncio task alongside the channel and jobs. Uses the same
notify callback pattern as jobs (channel.send injected by core).
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.bot.memory.database import Database

logger = logging.getLogger("synapulse.core.reminder")

_POLL_INTERVAL = 30  # seconds
_RECURRENCE_DELTAS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}

# Callback type: (channel_id, message) -> None
_NotifyCallback = Callable[[str, str], Coroutine[Any, Any, None]]


async def start_reminder_checker(db: Database, notify: _NotifyCallback) -> None:
    """Poll for due reminders and fire them. Runs forever as a background task.

    On first run, fires any overdue reminders immediately with a [Delayed] tag.
    """
    logger.info("Reminder checker started (poll every %ds)", _POLL_INTERVAL)

    while True:
        try:
            due = await db.get_due_reminders()
            for r in due:
                await _fire_reminder(db, notify, r)
        except Exception:
            logger.exception("Error in reminder checker loop")

        await asyncio.sleep(_POLL_INTERVAL)


async def _fire_reminder(
        db: Database, notify: _NotifyCallback, reminder: dict,
) -> None:
    """Fire a single reminder: send notification, mark fired, handle recurrence."""
    reminder_id = reminder["id"]
    channel_id = reminder["channel_id"]
    message = reminder["message"]
    remind_at = reminder["remind_at"]
    recurrence = reminder.get("recurrence")

    # Check if overdue (more than 1 minute late)
    try:
        dt = datetime.fromisoformat(remind_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delay = datetime.now(timezone.utc) - dt
        prefix = "[Delayed] " if delay > timedelta(minutes=1) else ""
    except (ValueError, TypeError):
        prefix = ""

    notification = f"\u23f0 {prefix}Reminder: {message}"

    try:
        await notify(channel_id, notification)
        logger.info("Fired reminder #%d: %s", reminder_id, message)
    except Exception:
        logger.exception("Failed to fire reminder #%d", reminder_id)
        return  # Don't mark as fired if notification failed

    await db.mark_reminder_fired(reminder_id)

    # Handle recurrence: create next occurrence
    if recurrence and recurrence in _RECURRENCE_DELTAS:
        try:
            dt = datetime.fromisoformat(remind_at)
            next_dt = dt + _RECURRENCE_DELTAS[recurrence]
            next_at = next_dt.isoformat()
            new_id = await db.create_reminder(
                reminder["user_id"], channel_id, next_at, message, recurrence,
            )
            logger.info("Recurring reminder #%d → next #%d at %s", reminder_id, new_id, next_at)
        except Exception:
            logger.exception("Failed to schedule recurring reminder #%d", reminder_id)
