"""Reminder tool — create, list, and cancel timed reminders.

Supports both absolute (ISO 8601) and relative (+5m, +1h30m) time formats.
Relative time is resolved server-side via datetime.now() — AI does not need
to know the current time.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from apps.bot.tool.base import AnthropicTool, OpenAITool

logger = logging.getLogger("synapulse.tool.reminder")

_DEFAULT_USER = "default"

# Matches "+5m", "+1h", "+2h30m", "+1d12h", "+1d2h30m", etc.
_RELATIVE_RE = re.compile(
    r"^\+(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$"
)


def _parse_relative(remind_at: str) -> datetime | None:
    """Try to parse a relative time offset like +5m, +1h30m, +1d.

    Returns absolute datetime (UTC) or None if not a relative format.
    """
    m = _RELATIVE_RE.match(remind_at.strip())
    if not m:
        return None
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    if days == 0 and hours == 0 and minutes == 0:
        return None  # "+0m" or bare "+" is invalid
    return datetime.now(timezone.utc) + timedelta(days=days, hours=hours, minutes=minutes)


def _parse_absolute(remind_at: str) -> datetime:
    """Parse ISO 8601 timestamp string into datetime. Raises ValueError on failure."""
    for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M%z",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(remind_at, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: '{remind_at}'")


def _parse_time(remind_at: str) -> datetime:
    """Parse remind_at as relative (+5m) or absolute (ISO 8601).

    Relative formats are resolved to absolute datetime server-side.
    """
    # Try relative first (cheap regex check)
    dt = _parse_relative(remind_at)
    if dt:
        return dt
    return _parse_absolute(remind_at)


def _format_time(iso: str) -> str:
    """Format ISO timestamp for display."""
    try:
        dt = _parse_absolute(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


class Tool(OpenAITool, AnthropicTool):
    name = "reminder"
    description = (
        "Manage reminders. "
        "Actions: create (set a timed reminder), list (show pending reminders), "
        "cancel (remove a reminder by ID). "
        "Time supports relative offset (+5m, +1h, +2h30m, +1d) "
        "or absolute ISO 8601 (e.g. 2026-03-10T15:00:00). "
        "Mode: 'notify' for passive reminders (e.g. 喝水), "
        "'prompt' when the bot should act on it (e.g. 告诉我天气)."
    )
    usage_hint = (
        "Set, list, or cancel reminders. "
        "For 'in X minutes/hours' requests, use relative time: +5m, +1h, +2h30m, +1d. "
        "For specific date/time, use ISO 8601: 2026-03-10T15:00:00. "
        "The tool resolves relative time automatically — do NOT calculate time yourself. "
        "Use mode='notify' for passive nudges (提醒我喝水, 提醒我开会). "
        "Use mode='prompt' when the user wants the bot to DO something at that time "
        "(告诉我现在时间, 帮我查天气, 总结今天的任务)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "cancel"],
                "description": (
                    "create: set a new reminder (requires remind_at + message); "
                    "list: show pending reminders; "
                    "cancel: cancel a reminder by ID"
                ),
            },
            "remind_at": {
                "type": "string",
                "description": (
                    "When to remind. "
                    "Relative: +5m, +1h, +2h30m, +1d (offset from now). "
                    "Absolute: ISO 8601 (e.g. 2026-03-10T15:00:00)."
                ),
            },
            "message": {
                "type": "string",
                "description": "Reminder message text",
            },
            "recurrence": {
                "type": "string",
                "enum": ["daily", "weekly"],
                "description": "Optional recurrence pattern",
            },
            "mode": {
                "type": "string",
                "enum": ["notify", "prompt"],
                "description": (
                    "notify (default): send static text reminder. "
                    "prompt: feed message to AI as user input when reminder fires "
                    "(use when user wants the bot to DO something, e.g. check weather, tell time)."
                ),
            },
            "reminder_id": {
                "type": "integer",
                "description": "Reminder ID (required for cancel)",
            },
        },
        "required": ["action"],
    }

    # channel_id is injected per-mention by core (same as send_file pattern)
    channel_id: str = ""

    def validate(self) -> None:
        # db is injected by core after scan_tools(), so not available here.
        pass

    async def execute(
            self, action: str, remind_at: str = "", message: str = "",
            recurrence: str | None = None, mode: str = "notify",
            reminder_id: int = 0,
    ) -> str:
        if not self.db:
            return "Error: database not available"
        if action == "create":
            return await self._create(remind_at, message, recurrence, mode)
        if action == "list":
            return await self._list()
        if action == "cancel":
            return await self._cancel(reminder_id)
        return f"Error: unknown action '{action}'"

    async def _create(self, remind_at: str, message: str, recurrence: str | None, mode: str) -> str:
        if not remind_at:
            return "Error: 'remind_at' is required (e.g. +5m, +1h, or 2026-03-10T15:00:00)"
        if not message:
            return "Error: 'message' is required for create action"

        # Parse time — supports both relative (+5m) and absolute (ISO 8601)
        try:
            dt = _parse_time(remind_at)
        except ValueError as e:
            return (
                f"Error: {e}. Use relative (+5m, +1h, +2h30m) "
                f"or ISO 8601 (2026-03-10T15:00:00)."
            )

        # Convert to ISO 8601 string for storage
        remind_at_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")

        # Warn if time is in the past (but still allow — checker will fire immediately)
        dt_aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if dt_aware < now:
            logger.warning("Reminder time is in the past: %s", remind_at_iso)

        # Validate mode
        if mode not in ("notify", "prompt"):
            mode = "notify"

        reminder_id = await self.db.create_reminder(
            _DEFAULT_USER, self.channel_id, remind_at_iso, message, recurrence, mode,
        )
        display = _format_time(remind_at_iso)
        recur_note = f" (repeats {recurrence})" if recurrence else ""
        mode_note = " [AI will process]" if mode == "prompt" else ""
        logger.info("Created reminder #%d at %s%s (mode=%s)", reminder_id, display, recur_note, mode)
        return f"Reminder #{reminder_id} set for {display}{recur_note}{mode_note}: {message}"

    async def _list(self) -> str:
        reminders = await self.db.list_reminders(_DEFAULT_USER)
        if not reminders:
            return "No pending reminders."
        lines = []
        for r in reminders:
            display = _format_time(r["remind_at"])
            recur = f" (repeats {r['recurrence']})" if r.get("recurrence") else ""
            lines.append(f"#{r['id']} [{display}]{recur} {r['message']}")
        return "\n".join(lines)

    async def _cancel(self, reminder_id: int) -> str:
        if not reminder_id:
            return "Error: 'reminder_id' is required for cancel action"
        cancelled = await self.db.cancel_reminder(reminder_id)
        if cancelled:
            logger.info("Cancelled reminder #%d", reminder_id)
            return f"Cancelled reminder #{reminder_id}."
        return f"Reminder #{reminder_id} not found or already fired."
