"""Persistent storage for conversations, memos, and reminders.

JSON file-based storage — one file per data type under a configurable directory.
Single Database class, created once by core at startup, injected into tools and
mention handler. Imports nothing from core, channel, provider, tool, or job.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("synapulse.memory")

_CONVERSATIONS_FILE = "conversations.json"
_SUMMARIES_FILE = "summaries.json"
_MEMOS_FILE = "memos.json"
_REMINDERS_FILE = "reminders.json"


def _now() -> str:
    """ISO 8601 timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> list | dict:
    """Load JSON file, return empty list if not exists or corrupt."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if text.strip() else []
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt or unreadable file: %s, starting fresh", path)
        return []


def _save_json(path: Path, data: list | dict) -> None:
    """Write JSON data to file."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Database:
    """JSON file-based persistent storage."""

    def __init__(self) -> None:
        self._dir: Path | None = None
        self._next_ids: dict[str, int] = {}

    async def init(self, path: str) -> None:
        """Initialize storage directory. path is treated as a directory for JSON files."""
        # Strip trailing filename if user configured a .db path (backward compat)
        p = Path(path)
        self._dir = p.parent if p.suffix else p
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("Storage directory: %s", self._dir)

        # Compute next IDs from existing data
        self._next_ids = {
            "conversations": self._max_id(_CONVERSATIONS_FILE) + 1,
            "memos": self._max_id(_MEMOS_FILE) + 1,
            "reminders": self._max_id(_REMINDERS_FILE) + 1,
        }
        logger.info("Database ready (JSON file storage)")

    def _max_id(self, filename: str) -> int:
        """Find the highest ID in a JSON file."""
        data = _load_json(self._dir / filename)
        if not data:
            return 0
        return max(item.get("id", 0) for item in data)

    def _next_id(self, collection: str) -> int:
        """Get and increment the next ID for a collection."""
        nid = self._next_ids.get(collection, 1)
        self._next_ids[collection] = nid + 1
        return nid

    def _path(self, filename: str) -> Path:
        return self._dir / filename

    async def close(self) -> None:
        """No-op for JSON storage (files are written on each mutation)."""
        logger.info("Database closed")

    # --- Conversations (F-01) ---

    async def save_turn(
            self, user_id: str, channel_id: str, role: str,
            content: str, tool_summary: str = "",
    ) -> None:
        """Save one conversation turn."""
        path = self._path(_CONVERSATIONS_FILE)
        data = _load_json(path)
        data.append({
            "id": self._next_id("conversations"),
            "user_id": user_id,
            "channel_id": channel_id,
            "role": role,
            "content": content,
            "tool_summary": tool_summary or None,
            "created_at": _now(),
        })
        _save_json(path, data)
        logger.debug("Saved turn: user=%s channel=%s role=%s len=%d",
                     user_id, channel_id, role, len(content))

    async def load_turns(
            self, user_id: str, channel_id: str, limit: int = 20,
    ) -> list[dict]:
        """Load recent conversation turns, oldest first."""
        data = _load_json(self._path(_CONVERSATIONS_FILE))
        matching = [
            t for t in data
            if t["user_id"] == user_id and t["channel_id"] == channel_id
        ]
        # Sort by created_at, take last N, return in chronological order
        matching.sort(key=lambda t: t["created_at"])
        return matching[-limit:]

    async def count_turns(self, user_id: str, channel_id: str) -> int:
        """Count total conversation turns for a user+channel."""
        data = _load_json(self._path(_CONVERSATIONS_FILE))
        return sum(
            1 for t in data
            if t["user_id"] == user_id and t["channel_id"] == channel_id
        )

    async def clear_turns(
            self, user_id: str, channel_id: str, before: str | None = None,
    ) -> int:
        """Delete conversation turns. If before is set, only delete turns before that timestamp."""
        path = self._path(_CONVERSATIONS_FILE)
        data = _load_json(path)
        original_count = len(data)

        if before:
            data = [
                t for t in data
                if not (t["user_id"] == user_id and t["channel_id"] == channel_id
                        and t["created_at"] < before)
            ]
        else:
            data = [
                t for t in data
                if not (t["user_id"] == user_id and t["channel_id"] == channel_id)
            ]

        deleted = original_count - len(data)
        _save_json(path, data)
        logger.info("Cleared %d turns: user=%s channel=%s", deleted, user_id, channel_id)
        return deleted

    # --- Summaries (F-02) ---

    async def save_summary(self, user_id: str, channel_id: str, content: str) -> None:
        """Upsert conversation summary (one per user+channel)."""
        path = self._path(_SUMMARIES_FILE)
        data = _load_json(path)

        # Find and update existing, or append new
        for item in data:
            if item["user_id"] == user_id and item["channel_id"] == channel_id:
                item["content"] = content
                item["updated_at"] = _now()
                _save_json(path, data)
                logger.info("Updated summary: user=%s channel=%s len=%d",
                            user_id, channel_id, len(content))
                return

        data.append({
            "user_id": user_id,
            "channel_id": channel_id,
            "content": content,
            "updated_at": _now(),
        })
        _save_json(path, data)
        logger.info("Saved summary: user=%s channel=%s len=%d", user_id, channel_id, len(content))

    async def load_summary(self, user_id: str, channel_id: str) -> str | None:
        """Load conversation summary, or None if not exists."""
        data = _load_json(self._path(_SUMMARIES_FILE))
        for item in data:
            if item["user_id"] == user_id and item["channel_id"] == channel_id:
                return item["content"]
        return None

    async def delete_summary(self, user_id: str, channel_id: str) -> None:
        """Delete conversation summary."""
        path = self._path(_SUMMARIES_FILE)
        data = _load_json(path)
        data = [
            s for s in data
            if not (s["user_id"] == user_id and s["channel_id"] == channel_id)
        ]
        _save_json(path, data)

    # --- Memos (F-03) ---

    async def save_memo(self, user_id: str, content: str) -> int:
        """Save a memo, return its ID."""
        path = self._path(_MEMOS_FILE)
        data = _load_json(path)
        now = _now()
        memo_id = self._next_id("memos")
        data.append({
            "id": memo_id,
            "user_id": user_id,
            "content": content,
            "created_at": now,
            "updated_at": now,
        })
        _save_json(path, data)
        logger.info("Saved memo #%d for user=%s", memo_id, user_id)
        return memo_id

    async def list_memos(self, user_id: str, limit: int = 20) -> list[dict]:
        """List memos for a user, newest first."""
        data = _load_json(self._path(_MEMOS_FILE))
        matching = [m for m in data if m["user_id"] == user_id]
        matching.sort(key=lambda m: m["created_at"], reverse=True)
        return matching[:limit]

    async def search_memos(self, user_id: str, query: str) -> list[dict]:
        """Search memos by keyword (case-insensitive match)."""
        data = _load_json(self._path(_MEMOS_FILE))
        query_lower = query.lower()
        matching = [
            m for m in data
            if m["user_id"] == user_id and query_lower in m["content"].lower()
        ]
        matching.sort(key=lambda m: m["created_at"], reverse=True)
        return matching[:20]

    async def delete_memo(self, memo_id: int) -> bool:
        """Delete a memo by ID. Returns True if deleted."""
        path = self._path(_MEMOS_FILE)
        data = _load_json(path)
        new_data = [m for m in data if m["id"] != memo_id]
        if len(new_data) == len(data):
            return False
        _save_json(path, new_data)
        logger.info("Deleted memo #%d", memo_id)
        return True

    # --- Reminders (F-04) ---

    async def create_reminder(
            self, user_id: str, channel_id: str,
            remind_at: str, message: str, recurrence: str | None = None,
    ) -> int:
        """Create a reminder, return its ID."""
        path = self._path(_REMINDERS_FILE)
        data = _load_json(path)
        reminder_id = self._next_id("reminders")
        data.append({
            "id": reminder_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "message": message,
            "remind_at": remind_at,
            "recurrence": recurrence,
            "fired": 0,
            "created_at": _now(),
        })
        _save_json(path, data)
        logger.info("Created reminder #%d for user=%s at %s", reminder_id, user_id, remind_at)
        return reminder_id

    async def list_reminders(self, user_id: str) -> list[dict]:
        """List unfired reminders for a user."""
        data = _load_json(self._path(_REMINDERS_FILE))
        matching = [
            r for r in data
            if r["user_id"] == user_id and r["fired"] == 0
        ]
        matching.sort(key=lambda r: r["remind_at"])
        return matching

    async def cancel_reminder(self, reminder_id: int) -> bool:
        """Cancel (delete) a reminder by ID. Returns True if deleted."""
        path = self._path(_REMINDERS_FILE)
        data = _load_json(path)
        new_data = [r for r in data if not (r["id"] == reminder_id and r["fired"] == 0)]
        if len(new_data) == len(data):
            return False
        _save_json(path, new_data)
        logger.info("Cancelled reminder #%d", reminder_id)
        return True

    async def get_due_reminders(self) -> list[dict]:
        """Get all unfired reminders whose time has come."""
        now = _now()
        data = _load_json(self._path(_REMINDERS_FILE))
        return [
            r for r in data
            if r["fired"] == 0 and r["remind_at"] <= now
        ]

    async def mark_reminder_fired(self, reminder_id: int) -> None:
        """Mark a reminder as fired."""
        path = self._path(_REMINDERS_FILE)
        data = _load_json(path)
        for r in data:
            if r["id"] == reminder_id:
                r["fired"] = 1
                break
        _save_json(path, data)
