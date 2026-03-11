"""Background reminder checker — polls for due reminders and fires them.

Runs as an asyncio task alongside the channel and jobs. Uses the same
notify callback pattern as jobs (channel.send injected by core).

Supports two firing modes:
- notify: send static text notification (default, backward compatible)
- prompt: feed message to AI as user input, send AI's response to channel
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
# Callback type: (content, channel_id) -> str (returns AI response)
_PromptCallback = Callable[[str, str], Coroutine[Any, Any, str]]


async def start_reminder_checker(
        db: Database,
        notify: _NotifyCallback,
        on_prompt: _PromptCallback | None = None,
) -> None:
    """Poll for due reminders and fire them. Runs forever as a background task.

    Args:
        notify: Send a static text message to a channel.
        on_prompt: Feed a message to the AI tool-call loop, return AI's response.
            Required for prompt-mode reminders. If None, prompt-mode falls back to notify.
    """
    logger.info("Reminder checker started (poll every %ds)", _POLL_INTERVAL)

    while True:
        try:
            due = await db.get_due_reminders()
            for r in due:
                await _fire_reminder(db, notify, on_prompt, r)
        except Exception:
            logger.exception("Error in reminder checker loop")

        await asyncio.sleep(_POLL_INTERVAL)


async def _fire_reminder(
        db: Database,
        notify: _NotifyCallback,
        on_prompt: _PromptCallback | None,
        reminder: dict,
) -> None:
    """Fire a single reminder: send notification or prompt AI, mark fired, handle recurrence."""
    reminder_id = reminder["id"]
    channel_id = reminder["channel_id"]
    message = reminder["message"]
    remind_at = reminder["remind_at"]
    recurrence = reminder.get("recurrence")
    mode = reminder.get("mode", "notify")  # backward compat: default to notify

    # Check if overdue (more than 1 minute late)
    try:
        dt = datetime.fromisoformat(remind_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delay = datetime.now(timezone.utc) - dt
        prefix = "[Delayed] " if delay > timedelta(minutes=1) else ""
    except (ValueError, TypeError):
        prefix = ""

    try:
        delayed_tag = " ⚡" if prefix else ""

        if mode == "prompt" and on_prompt:
            # Prompt mode: feed message to AI, send the AI's response
            logger.info("Firing prompt-mode reminder #%d: %s", reminder_id, message)
            ai_response = await on_prompt(message, channel_id)
            notification = (
                f"🔔📋{delayed_tag}\n"
                f"╭───────────────\n"
                f"│ *{message}*\n"
                f"╰───────────────\n\n"
                f"{ai_response}"
            )
            await notify(channel_id, notification)
        else:
            # Notify mode (default): send static text
            notification = (
                f"🔔💡{delayed_tag}\n"
                f"╭───────────────\n"
                f"│ {message}\n"
                f"╰───────────────"
            )
            await notify(channel_id, notification)

        logger.info("Fired reminder #%d (mode=%s): %s", reminder_id, mode, message)
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
                reminder["user_id"], channel_id, next_at, message, recurrence, mode,
            )
            logger.info("Recurring reminder #%d → next #%d at %s", reminder_id, new_id, next_at)
        except Exception:
            logger.exception("Failed to schedule recurring reminder #%d", reminder_id)
