"""Memo tool — persistent notes and knowledge base for the user.

Lets the AI save, search, list, and delete user memos.
All data persisted in JSON files via the injected Database instance.
"""

import logging

from apps.bot.tool.base import AnthropicTool, OpenAITool

logger = logging.getLogger("synapulse.tool.memo")

# Single-user for now; field exists for future multi-user support.
_DEFAULT_USER = "default"
_MAX_MEMOS = 1000


class Tool(OpenAITool, AnthropicTool):
    name = "memo"
    description = (
        "Manage user memos (personal notes and knowledge base). "
        "Actions: save (store a note), list (show recent notes), "
        "search (find notes by keyword), delete (remove a note by ID), "
        "clear_history (clear conversation history for current channel)."
    )
    usage_hint = (
        "Save, recall, search, or delete personal notes and facts. "
        "Use when the user asks you to remember something or recall a saved fact. "
        "Also use clear_history when user asks to forget/clear conversation history."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save", "list", "search", "delete", "clear_history"],
                "description": (
                    "save: store a new memo; "
                    "list: show recent memos; "
                    "search: find memos by keyword; "
                    "delete: remove a memo by ID; "
                    "clear_history: clear conversation history (not memos)"
                ),
            },
            "content": {
                "type": "string",
                "description": "Memo text (for save) or search keyword (for search)",
            },
            "memo_id": {
                "type": "integer",
                "description": "Memo ID (required for delete)",
            },
        },
        "required": ["action"],
    }

    def validate(self) -> None:
        # db is injected by core after scan_tools(), so not available here.
        pass

    # channel_id injected per-mention by core (for clear_history scope)
    channel_id: str = ""

    async def execute(self, action: str, content: str = "", memo_id: int = 0) -> str:
        if not self.db:
            return "Error: database not available"
        if action == "save":
            return await self._save(content)
        if action == "list":
            return await self._list()
        if action == "search":
            return await self._search(content)
        if action == "delete":
            return await self._delete(memo_id)
        if action == "clear_history":
            return await self._clear_history()
        return f"Error: unknown action '{action}'"

    async def _save(self, content: str) -> str:
        if not content:
            return "Error: 'content' is required for save action"

        # Check entry limit
        existing = await self.db.list_memos(_DEFAULT_USER, limit=_MAX_MEMOS)
        if len(existing) >= _MAX_MEMOS:
            return f"Error: memo limit reached ({_MAX_MEMOS}). Please delete old memos first."

        # Check for duplicates (exact content match)
        for m in existing[:50]:  # check recent 50 for near-duplicates
            if m["content"].strip().lower() == content.strip().lower():
                return f"A similar memo already exists: #{m['id']} — {m['content'][:80]}"

        memo_id = await self.db.save_memo(_DEFAULT_USER, content)
        logger.info("Saved memo #%d", memo_id)
        return f"Saved memo #{memo_id}."

    async def _list(self) -> str:
        memos = await self.db.list_memos(_DEFAULT_USER)
        if not memos:
            return "No memos saved yet."
        lines = []
        for m in memos:
            lines.append(f"#{m['id']} [{m['created_at'][:10]}] {m['content']}")
        return "\n".join(lines)

    async def _search(self, query: str) -> str:
        if not query:
            return "Error: 'content' with search keyword is required for search action"
        memos = await self.db.search_memos(_DEFAULT_USER, query)
        if not memos:
            return f"No memos matching '{query}'."
        lines = []
        for m in memos:
            lines.append(f"#{m['id']} [{m['created_at'][:10]}] {m['content']}")
        return "\n".join(lines)

    async def _delete(self, memo_id: int) -> str:
        if not memo_id:
            return "Error: 'memo_id' is required for delete action"
        deleted = await self.db.delete_memo(memo_id)
        if deleted:
            logger.info("Deleted memo #%d", memo_id)
            return f"Deleted memo #{memo_id}."
        return f"Memo #{memo_id} not found."

    async def _clear_history(self) -> str:
        """Clear conversation history for current user+channel. Does NOT clear memos."""
        if not self.channel_id:
            return "Error: channel context not available"
        count = await self.db.clear_turns(_DEFAULT_USER, self.channel_id)
        await self.db.delete_summary(_DEFAULT_USER, self.channel_id)
        logger.info("Cleared history: %d turns + summary for channel=%s", count, self.channel_id)
        return f"Cleared {count} conversation turns and summary. Memos are preserved."
