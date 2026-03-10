"""Reminder tool — create, list, and cancel timed reminders.

AI resolves natural language time into ISO 8601 timestamps.
The tool validates and stores them; a background checker fires them.
"""

import logging
from datetime import datetime, timezone

from apps.bot.tool.base import AnthropicTool, OpenAITool

logger = logging.getLogger("synapulse.tool.reminder")

_DEFAULT_USER = "default"


def _parse_time(remind_at: str) -> datetime:
    """Parse ISO 8601 timestamp string into datetime. Raises ValueError on failure."""
    # Accept common formats: with/without timezone, with/without seconds
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


def _format_time(iso: str) -> str:
    """Format ISO timestamp for display."""
    try:
        dt = _parse_time(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


class Tool(OpenAITool, AnthropicTool):
    name = "reminder"
    description = (
        "Manage reminders. "
        "Actions: create (set a timed reminder), list (show pending reminders), "
        "cancel (remove a reminder by ID). "
        "Time must be in ISO 8601 format (e.g. 2026-03-10T15:00:00)."
    )
    usage_hint = (
        "Set, list, or cancel reminders. AI must convert natural language time "
        "to ISO 8601 format before calling create."
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
                "description": "ISO 8601 datetime for the reminder (e.g. 2026-03-10T15:00:00)",
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
            recurrence: str | None = None, reminder_id: int = 0,
    ) -> str:
        if not self.db:
            return "Error: database not available"
        if action == "create":
            return await self._create(remind_at, message, recurrence)
        if action == "list":
            return await self._list()
        if action == "cancel":
            return await self._cancel(reminder_id)
        return f"Error: unknown action '{action}'"

    async def _create(self, remind_at: str, message: str, recurrence: str | None) -> str:
        if not remind_at:
            return "Error: 'remind_at' (ISO 8601 datetime) is required for create action"
        if not message:
            return "Error: 'message' is required for create action"

        # Validate timestamp format
        try:
            dt = _parse_time(remind_at)
        except ValueError as e:
            return f"Error: {e}. Please use ISO 8601 format (e.g. 2026-03-10T15:00:00)."

        # Warn if time is in the past (but still allow — checker will fire immediately)
        # Ensure both are timezone-aware for comparison
        dt_aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if dt_aware < now:
            logger.warning("Reminder time is in the past: %s", remind_at)

        reminder_id = await self.db.create_reminder(
            _DEFAULT_USER, self.channel_id, remind_at, message, recurrence,
        )
        display = _format_time(remind_at)
        recur_note = f" (repeats {recurrence})" if recurrence else ""
        logger.info("Created reminder #%d at %s%s", reminder_id, display, recur_note)
        return f"Reminder #{reminder_id} set for {display}{recur_note}: {message}"

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
