# REQ-002 Technical Design

> Status: Completed
> Requirement: requirement.md
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Technology Stack

| Module             | Technology                                    | Rationale                                                                    |
|:-------------------|:----------------------------------------------|:-----------------------------------------------------------------------------|
| Persistent storage | JSON files (stdlib `json` + `pathlib`)        | Zero-config, zero external dependency, human-readable, trivially recoverable |
| Timestamp handling | Python `datetime` (stdlib)                    | AI provides ISO format strings, stdlib parses natively                       |
| Fuzzy text search  | Python `str` `in` operator (case-insensitive) | Good enough for single-user memo search, no extra dependency                 |

### New dependency

None. All storage uses Python stdlib (`json`, `pathlib`). No external packages required.

## 2. Design Principles

- **High cohesion, low coupling**: memory is a standalone data layer; core orchestrates; tools do CRUD
- **Reuse first**: single `Database` class handles all tables; tools and core share the same DB instance
- **Existing patterns preserved**: tools follow `tool/{name}/handler.py`, dynamic loading unchanged
- **Dependency direction**: `memory` imports nothing from core/channel/provider/tool/job. Both core and tools may import
  from memory
- **Graceful degradation**: all DB operations wrapped in try/except; failures logged, never crash the bot
- **IoC maintained**: core creates the DB instance and injects it into tools and mention handler

## 3. Architecture Overview

```
main.py → core/handler.py (bootstrap orchestrator)
               │
               ├── memory/database.py   ← NEW: JSON file storage operations
               │       ↑                    (conversations, memos, reminders)
               │       │
               ├── core/mention.py      ← MODIFIED: load/save conversation history
               │       │
               ├── core/reminder.py     ← NEW: background reminder checker
               │
               ├── tool/memo/handler.py     ← NEW: uses memory.database
               ├── tool/reminder/handler.py ← NEW: uses memory.database
               ├── tool/brave_search/       (unchanged)
               └── tool/local_files/        (unchanged)
```

Dependency direction (memory is the bottom layer):

```
core ──→ memory ←── tool/memo
core ──→ memory ←── tool/reminder
```

No circular dependencies. Memory knows nothing about who calls it.

## 4. Module Design

### 4.1 Memory Database (`apps/bot/memory/database.py`)

- **Responsibility**: All JSON file CRUD operations for conversations, memos, and reminders
- **Public interface**:
  ```
  class Database:
      async def init(path: str) -> None
          # Create storage directory, compute next IDs from existing data

      # --- Conversations (F-01) ---
      async def save_turn(user_id, channel_id, role, content, tool_summary) -> None
      async def load_turns(user_id, channel_id, limit=20) -> list[dict]
      async def clear_turns(user_id, channel_id, before: str | None) -> int
      async def count_turns(user_id, channel_id) -> int

      # --- Summaries (F-02) ---
      async def save_summary(user_id, channel_id, content) -> None
      async def load_summary(user_id, channel_id) -> str | None
      async def delete_summary(user_id, channel_id) -> None

      # --- Memos (F-03) ---
      async def save_memo(user_id, content) -> int  # returns memo id
      async def list_memos(user_id, limit=20) -> list[dict]
      async def search_memos(user_id, query) -> list[dict]
      async def delete_memo(memo_id) -> bool

      # --- Reminders (F-04) ---
      async def create_reminder(user_id, channel_id, remind_at, message, recurrence) -> int
      async def list_reminders(user_id) -> list[dict]
      async def cancel_reminder(reminder_id) -> bool
      async def get_due_reminders() -> list[dict]
      async def mark_reminder_fired(reminder_id) -> None

      async def close() -> None
  ```
- **Internal structure**: Single class, four JSON files (`conversations.json`, `summaries.json`, `memos.json`,
  `reminders.json`), auto-incrementing IDs via in-memory `_next_ids` dict, helper functions `_load_json()` /
  `_save_json()` for file I/O
- **Reuse notes**: Shared by core (conversation load/save/summarize), tool/memo, tool/reminder, core/reminder checker

### 4.2 Mention Handler Changes (`apps/bot/core/mention.py`)

- **Responsibility**: Extended to load conversation history before AI call, save turn after AI responds
- **Changes**:
    - `make_mention_handler` receives additional `db: Database` parameter
    - Before building messages: load conversation history + summary from DB, inject into user prompt context
    - After AI returns final text: save the turn (user message + AI reply + tool call summary) to DB
    - After save: check turn count, trigger summarization if threshold exceeded
- **Token budget**: Conversation context injected as a block with configurable max character limit (default 3000
  chars ≈ ~750 tokens). Summary capped at 2000 chars (~500 tokens)

### 4.3 Conversation Summarizer (`apps/bot/core/mention.py` — internal function)

- **Responsibility**: Compress old conversation turns into a summary using the AI provider
- **Flow**:
    1. `count_turns()` > threshold (20) → trigger
    2. Load all turns, keep most recent 5, feed rest to AI with summarization prompt
    3. AI returns summary → `save_summary()` + `clear_turns()` for summarized turns
    4. On failure: log warning, keep raw turns (truncate on next load if needed)
- **Summarization prompt**: Short, directive — "Summarize this conversation. Include: key topics, user preferences,
  important facts. Max 500 words."
- **Not a separate module**: Lives as a private async function in `mention.py` since it uses the provider that's already
  closed over

### 4.4 Memo Tool (`apps/bot/tool/memo/handler.py`)

- **Responsibility**: AI tool for user notes/knowledge base CRUD
- **Public interface**: Standard tool contract (`name`, `description`, `parameters`, `execute`)
- **Actions**:
    - `save(content)` → `db.save_memo(user_id, content)` → "Saved memo #id"
    - `list()` → `db.list_memos(user_id)` → formatted list
    - `search(query)` → `db.search_memos(user_id, query)` → matching entries
    - `delete(memo_id)` → `db.delete_memo(id)` → "Deleted" or "Not found"
- **DB injection**: `db` attribute set by core at startup (same pattern as `send_file`)
- **user_id**: Hardcoded to `"default"` for now (single user); field exists for future multi-user

### 4.5 Reminder Tool (`apps/bot/tool/reminder/handler.py`)

- **Responsibility**: AI tool for creating, listing, and cancelling reminders
- **Actions**:
    - `create(remind_at, message, recurrence?)` → `db.create_reminder(...)` → "Reminder #id set for ..."
    - `list()` → `db.list_reminders(user_id)` → formatted list with IDs
    - `cancel(reminder_id)` → `db.cancel_reminder(id)` → "Cancelled" or "Not found"
- **Time handling**: AI resolves natural language to ISO 8601 timestamp string. Tool parses and validates. Invalid →
  error string back to AI
- **Recurrence**: Optional field — `null` (one-time), `"daily"`, `"weekly"`. Stored as string. Checker handles
  re-scheduling after fire

### 4.6 Reminder Checker (`apps/bot/core/reminder.py`)

- **Responsibility**: Background asyncio task that polls DB for due reminders and fires them
- **Flow**:
    1. `start(db, notify)` — launched by `core/handler.py` as `asyncio.create_task`
    2. Loop: sleep 30s → `db.get_due_reminders()` → for each: `notify(channel_id, message)` →
       `db.mark_reminder_fired(id)`
    3. For recurring reminders: after firing, compute next occurrence and create new reminder entry
    4. On startup: check for overdue reminders, fire immediately with `[Delayed]` prefix
- **notify callback**: Same `channel.send` used by jobs — core injects it
- **Error handling**: Individual reminder fire failure logged, loop continues

### 4.7 System Prompt Enhancement (`apps/bot/config/prompts.py`)

- **Responsibility**: Dynamic system prompt assembly with memory context
- **Changes**:
    - New function `build_system_prompt(tools: dict, memory_summary: str | None) -> str`
    - Structure: `SYSTEM_PROMPT + BEHAVIOR_STRATEGY + TOOLS section + MEMORY section`
    - `BEHAVIOR_STRATEGY`: new constant with tool usage strategy, multi-step decomposition guidance
    - Memory section only added when `memory_summary` is not None/empty
    - `SYSTEM_PROMPT` Capabilities section updated to match actual tools
- **Moved from mention.py**: System prompt assembly logic currently in `make_mention_handler` moves to `prompts.py` for
  single responsibility

### 4.8 Bootstrap Changes (`apps/bot/core/handler.py`)

- **Responsibility**: Initialize DB, inject into tools and mention handler, start reminder checker
- **Changes** (in order within `start()`):
    1. After config: `db = Database(); await db.init(config.DATABASE_PATH)`
    2. After tool scan: inject `db` into memo and reminder tools
    3. After channel ready: start reminder checker task with `db` + `channel.send`
    4. `make_mention_handler` receives `db` parameter
- **Cleanup**: Register DB close on shutdown (no-op for JSON storage, but good practice for interface consistency)

### 4.9 Config Extension (`apps/bot/config/settings.py`)

- **New field**: `DATABASE_PATH: str` — default `"data/synapulse.db"`, loaded from `.env`
- **Auto-create**: `data/` directory created if not exists (by `Database.init()`)

## 5. Data Model

Storage: four JSON files under a configurable directory. Each file contains a JSON array of record objects.

### File: `conversations.json`

Each record:

| Field          | Type           | Description                                |
|:---------------|:---------------|:-------------------------------------------|
| `id`           | int            | Auto-increment                             |
| `user_id`      | string         | User identifier                            |
| `channel_id`   | string         | Channel identifier                         |
| `role`         | string         | "user" or "assistant"                      |
| `content`      | string         | Message content                            |
| `tool_summary` | string \| null | Comma-separated tool names used (nullable) |
| `created_at`   | string         | ISO 8601 timestamp                         |

Filtered by `(user_id, channel_id)`, sorted by `created_at`.

### File: `summaries.json`

Each record:

| Field        | Type   | Description          |
|:-------------|:-------|:---------------------|
| `user_id`    | string | User identifier      |
| `channel_id` | string | Channel identifier   |
| `content`    | string | AI-generated summary |
| `updated_at` | string | ISO 8601 timestamp   |

One summary per `(user_id, channel_id)` — upsert on save.

### File: `memos.json`

Each record:

| Field        | Type   | Description        |
|:-------------|:-------|:-------------------|
| `id`         | int    | Auto-increment     |
| `user_id`    | string | User identifier    |
| `content`    | string | Memo content       |
| `created_at` | string | ISO 8601 timestamp |
| `updated_at` | string | ISO 8601 timestamp |

Filtered by `user_id`, sorted by `created_at` descending (newest first).

### File: `reminders.json`

Each record:

| Field        | Type           | Description                |
|:-------------|:---------------|:---------------------------|
| `id`         | int            | Auto-increment             |
| `user_id`    | string         | User identifier            |
| `channel_id` | string         | Where to send notification |
| `message`    | string         | Reminder message           |
| `remind_at`  | string         | ISO 8601 timestamp         |
| `recurrence` | string \| null | null, "daily", or "weekly" |
| `fired`      | int            | 0 = pending, 1 = fired     |
| `created_at` | string         | ISO 8601 timestamp         |

Due reminders queried by `fired == 0 and remind_at <= now`.

## 6. API Design

No HTTP APIs. All interfaces are Python method calls within the same process.

### Tool Schemas (JSON Schema for AI function calling)

**memo tool:**

```json
{
  "type": "object",
  "properties": {
    "action": {"type": "string", "enum": ["save", "list", "search", "delete"]},
    "content": {"type": "string", "description": "Memo text (for save) or search query (for search)"},
    "memo_id": {"type": "integer", "description": "Memo ID (for delete)"}
  },
  "required": ["action"]
}
```

**reminder tool:**

```json
{
  "type": "object",
  "properties": {
    "action": {"type": "string", "enum": ["create", "list", "cancel"]},
    "message": {"type": "string", "description": "Reminder message"},
    "remind_at": {"type": "string", "description": "ISO 8601 datetime (e.g. 2026-03-10T15:00:00)"},
    "recurrence": {"type": "string", "enum": ["daily", "weekly"], "description": "Optional recurrence"},
    "reminder_id": {"type": "integer", "description": "Reminder ID (for cancel)"}
  },
  "required": ["action"]
}
```

## 7. Key Flows

### 7.1 Mention with Memory (F-01 + F-02 + F-05)

```
User @mentions bot
  → core/mention.py: load_turns(user_id, channel_id)
  → core/mention.py: load_summary(user_id, channel_id)
  → prompts.py: build_system_prompt(tools, summary)
  → Build user prompt with injected conversation history
  → Enter tool-call loop (unchanged)
  → AI returns text
  → core/mention.py: save_turn(user_id, channel_id, "user", content)
  → core/mention.py: save_turn(user_id, channel_id, "assistant", reply)
  → If count_turns > 20: trigger summarization
  → Return reply to Discord
```

### 7.2 Memo Save + Recall (F-03)

```
User: "remember my server IP is 192.168.1.1"
  → AI calls memo.save(content="User's server IP is 192.168.1.1")
  → tool/memo: db.save_memo("default", content) → returns id
  → AI: "Got it, saved as memo #5"

User: "what's my server IP?"
  → AI calls memo.search(content="server IP")
  → tool/memo: db.search_memos("default", "server IP") → returns matches
  → AI: "Your server IP is 192.168.1.1 (from memo #5)"
```

### 7.3 Reminder Lifecycle (F-04)

```
User: "remind me in 5 minutes to drink water"
  → AI resolves: remind_at = "2026-03-10T14:05:00"
  → AI calls reminder.create(remind_at=..., message="drink water")
  → tool/reminder: db.create_reminder(...) → returns id
  → AI: "Reminder #3 set for 2:05 PM"

  ... 5 minutes later ...

  → core/reminder.py checker: get_due_reminders() → finds #3
  → checker: notify(channel_id, "⏰ Reminder: drink water")
  → checker: mark_reminder_fired(3)
```

## 8. Shared Modules & Reuse Strategy

| Shared Component                            | Used By                                                     | How                                                                |
|:--------------------------------------------|:------------------------------------------------------------|:-------------------------------------------------------------------|
| `memory/database.py` (Database class)       | core/mention.py, core/reminder.py, tool/memo, tool/reminder | Single instance created in handler.py, injected into all consumers |
| `config.DATABASE_PATH`                      | memory/database.py                                          | Read at init time                                                  |
| `channel.send` callback                     | core/reminder.py, jobs                                      | Same notify callback pattern already used by jobs                  |
| `provider.chat` + `provider.build_messages` | core/mention.py (summarization)                             | Reuses existing provider for summary generation                    |

### Injection pattern

Core creates `Database` once → injects as attribute into tools (like `send_file` today):

```python
# In handler.py start()
db = Database()
await db.init(config.DATABASE_PATH)

for tool in tools.values():
    tool.db = db  # tools that don't need it simply ignore the attribute
```

This is consistent with the existing `send_file` injection pattern and avoids import-time coupling.

## 9. Risks & Notes

| Risk                                                 | Mitigation                                                                                                                        |
|:-----------------------------------------------------|:----------------------------------------------------------------------------------------------------------------------------------|
| JSON file I/O on every mutation                      | Single-user workload — file sizes stay small. Acceptable for personal assistant. If data grows large, can migrate to SQLite later |
| Summarization quality varies by AI model             | Summary prompt is simple and directive; cheap models (Ollama) may produce weaker summaries — acceptable for personal use          |
| Reminder checker polling interval (30s)              | Reminders may fire up to 30s late — acceptable for personal assistant. Not suitable for second-precision timing                   |
| Corrupt JSON file                                    | `_load_json()` handles corrupt/unreadable files gracefully — logs warning, returns empty list, starts fresh                       |
| Token budget overflow from long memory               | Hard cap on injected context size (3000 chars for history, 2000 chars for summary). Truncate from oldest if exceeded              |
| AI may not always call memo/reminder tools correctly | Tool descriptions and usage_hints provide clear guidance. Existing jsonschema validation catches bad arguments                    |

## 10. Change Log

| Version | Date       | Changes                                                                                                                                                   | Affected Scope                                                      | Reason                                               |
|:--------|:-----------|:----------------------------------------------------------------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------|:-----------------------------------------------------|
| v1      | 2026-03-10 | Initial version                                                                                                                                           | ALL                                                                 | -                                                    |
| v2      | 2026-03-10 | Storage changed from SQLite/aiosqlite to JSON files (stdlib). Removed aiosqlite dependency. Updated data model from SQL tables to JSON record structures. | Section 1, Module 4.1, Section 3, Section 4.8, Section 5, Section 9 | Simplify: zero external deps, human-readable storage |
