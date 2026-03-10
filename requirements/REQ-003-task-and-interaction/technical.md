# REQ-003 Technical Design

> Status: Completed
> Requirement: requirement.md
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Technology Stack

| Module                 | Technology                             | Rationale                                              |
|:-----------------------|:---------------------------------------|:-------------------------------------------------------|
| Persistent storage     | JSON files (stdlib `json` + `pathlib`) | Consistent with REQ-002, reuse existing Database class |
| Task context injection | Python string formatting               | Same pattern as memory summary injection in prompts.py |
| Message reference      | Discord.py `message.reference`         | Built-in Discord.py feature, zero extra dependency     |

### New dependency

None. All features use existing stdlib and Discord.py capabilities.

## 2. Design Principles

- **Reuse first**: Extend existing `Database` class with task CRUD methods. No new storage module.
- **Consistent patterns**: Task tool follows the exact same structure as memo/reminder tools — `tool/task/handler.py`,
  db injection, dynamic loading.
- **Minimal footprint for F-03**: Notification interaction requires only a small change in the Discord client's
  `on_message` handler — extract referenced message content and pass it through.
- **No new abstractions**: Task context injection follows the memory summary pattern in `build_system_prompt()` — add
  another optional section.

## 3. Architecture Overview

```
main.py → core/handler.py (bootstrap orchestrator)
               │
               ├── memory/database.py   ← EXTENDED: add tasks.json CRUD
               │       ↑
               │       │
               ├── core/mention.py      ← MODIFIED: load task context, handle referenced message
               │       │
               ├── config/prompts.py    ← MODIFIED: add task section to system prompt
               │
               ├── tool/task/handler.py     ← NEW: task management tool
               ├── tool/memo/handler.py     (unchanged)
               ├── tool/reminder/handler.py (unchanged)
               │
               └── channel/discord/client.py ← MODIFIED: extract message reference content
```

Dependency direction unchanged — memory is still the bottom layer:

```
core ──→ memory ←── tool/task
core ──→ memory ←── tool/memo
core ──→ memory ←── tool/reminder
```

## 4. Module Design

### 4.1 Database Extension (`apps/bot/memory/database.py`)

- **Responsibility**: Add task CRUD operations alongside existing conversations, memos, and reminders
- **Changes**:
    - New constant: `_TASKS_FILE = "tasks.json"`
    - Add `"tasks"` to `_next_ids` initialization in `init()`
    - New methods:
      ```
      async def save_task(user_id, title, description, priority, due_date) -> int
      async def list_tasks(user_id, status=None, priority=None, limit=20) -> list[dict]
      async def update_task(task_id, **fields) -> bool
      async def complete_task(task_id) -> bool
      async def delete_task(task_id) -> bool
      async def get_pending_tasks_summary(user_id, limit=20) -> list[dict]
      ```
- **Internal structure**: Same `_load_json()` / `_save_json()` pattern. Each task record:
  ```json
  {
    "id": 1,
    "user_id": "default",
    "title": "Submit report",
    "description": "",
    "status": "todo",
    "priority": "high",
    "due_date": "2026-03-14",
    "created_at": "2026-03-10T12:00:00+00:00",
    "updated_at": "2026-03-10T12:00:00+00:00"
  }
  ```
- **Reuse notes**: Shared by tool/task and core/mention.py (for task context injection)

### 4.2 Task Tool (`apps/bot/tool/task/handler.py`)

- **Responsibility**: AI tool for task CRUD operations
- **Public interface**: Standard tool contract (`name`, `description`, `parameters`, `execute`)
- **Actions**:
    - `create(title, description?, priority?, due_date?)` → `db.save_task(...)` → "Created task #id"
    - `list(status?, priority?)` → `db.list_tasks(...)` → formatted task list
    - `update(task_id, title?, description?, status?, priority?, due_date?)` → `db.update_task(...)` → "Updated" or "Not
      found"
    - `complete(task_id)` → `db.complete_task(...)` → "Completed" or "Not found"
    - `delete(task_id)` → `db.delete_task(...)` → "Deleted" or "Not found"
- **DB injection**: `db` attribute set by core at startup (existing pattern)
- **Validation**: `validate()` is no-op (db injected after scan, same as memo/reminder)
- **Guard rails**:
    - Task limit: `_MAX_TASKS = 500` — check before create
    - Duplicate detection: case-insensitive title match on recent tasks
    - Default list excludes completed tasks (unless `status="done"` is passed)

### 4.3 Mention Handler Changes (`apps/bot/core/mention.py`)

- **Responsibility**: Extended to load task context and handle referenced messages
- **Changes**:
    - Load pending tasks via `db.get_pending_tasks_summary()` before building system prompt
    - Pass task summary to `build_system_prompt()` as new parameter
    - Accept optional `referenced_content` parameter and inject into user prompt
- **Referenced content injection**: Prepend `[Referenced bot message]\n<content>` before user message in
  `_build_user_prompt()`
- **Token budget**: Task summary capped at `_TASK_CONTEXT_CAP = 1000` chars

### 4.4 System Prompt Enhancement (`apps/bot/config/prompts.py`)

- **Responsibility**: Add task context section to system prompt
- **Changes**:
    - `build_system_prompt()` receives new optional parameter `task_summary: str | None`
    - When present, inject `## Pending Tasks\n<summary>` section
    - Add task-related guidance to `BEHAVIOR_STRATEGY`:
        - "Use task tool to track to-dos, action items, and deadlines"
        - "When user asks about their schedule or what to do, check pending tasks"
        - "Do not create tasks for every request — only when user explicitly asks to track something"
- **Token budget**: `_TASK_SUMMARY_CAP = 1000` chars

### 4.5 Discord Client Changes (`apps/bot/channel/discord/client.py`)

- **Responsibility**: Extract referenced message content when user replies to a bot message
- **Changes in `on_message`**:
    1. Check `message.reference` (Discord.py MessageReference)
    2. If present, fetch the referenced message via `message.reference.resolved` or `channel.fetch_message()`
    3. If the referenced message is from the bot, extract its `.content`
    4. Truncate to 2000 chars if too long
    5. Pass as additional context to `on_mention()` callback
- **MentionHandler signature change**: Add optional `referenced_content: str | None` parameter
    - New signature: `(content, channel_id, user_id, history, referenced_content) -> reply`

### 4.6 Channel Base Update (`apps/bot/channel/base.py`)

- **Responsibility**: Update MentionHandler type to include referenced_content
- **Change**: Add `str | None` parameter to the MentionHandler type alias
  ```python
  MentionHandler = Callable[
      [str, str, str, list[dict[str, str]] | None, str | None],
      Coroutine[Any, Any, str],
  ]
  ```

### 4.7 Bootstrap (no changes needed)

- `core/handler.py` already injects `db` into all tools via the generic loop
- The new task tool will automatically receive `db` injection
- `scan_tools()` will auto-discover `tool/task/handler.py`
- No bootstrap changes required

## 5. Data Model

### File: `tasks.json` (NEW)

Each record:

| Field         | Type           | Description                                            |
|:--------------|:---------------|:-------------------------------------------------------|
| `id`          | int            | Auto-increment                                         |
| `user_id`     | string         | User identifier                                        |
| `title`       | string         | Task title                                             |
| `description` | string         | Detailed description (optional, default empty)         |
| `status`      | string         | "todo", "in_progress", or "done"                       |
| `priority`    | string         | "low", "medium", or "high"                             |
| `due_date`    | string \| null | ISO 8601 date (e.g. "2026-03-14"), null if no deadline |
| `created_at`  | string         | ISO 8601 timestamp                                     |
| `updated_at`  | string         | ISO 8601 timestamp                                     |

Default list filtered by `status != "done"`, sorted by priority (high > medium > low) then `due_date` ascending (
earliest first, null last).

## 6. API Design

No HTTP APIs. All interfaces are Python method calls within the same process.

### Tool Schema (JSON Schema for AI function calling)

**task tool:**

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["create", "list", "update", "complete", "delete"]
    },
    "task_id": {
      "type": "integer",
      "description": "Task ID (for update, complete, delete)"
    },
    "title": {
      "type": "string",
      "description": "Task title (for create, update)"
    },
    "description": {
      "type": "string",
      "description": "Task description (for create, update)"
    },
    "status": {
      "type": "string",
      "enum": ["todo", "in_progress", "done"],
      "description": "Task status (for list filter, update)"
    },
    "priority": {
      "type": "string",
      "enum": ["low", "medium", "high"],
      "description": "Task priority (for create, update, list filter)"
    },
    "due_date": {
      "type": "string",
      "description": "Due date in ISO 8601 format, e.g. 2026-03-14 (for create, update)"
    }
  },
  "required": ["action"]
}
```

## 7. Key Flows

### 7.1 Task Create + List (F-01)

```
User: "add a task: submit report by Friday, high priority"
  → AI resolves: title="Submit report", due_date="2026-03-14", priority="high"
  → AI calls task.create(title=..., due_date=..., priority=...)
  → tool/task: db.save_task(...) → returns id
  → AI: "Created task #1: Submit report (high priority, due 2026-03-14)"

User: "what are my tasks?"
  → AI calls task.list()
  → tool/task: db.list_tasks("default") → returns pending tasks
  → AI: "You have 3 pending tasks: #1 Submit report (high, due Mar 14)..."
```

### 7.2 Task Context Injection (F-02)

```
User @mentions bot with any message
  → core/mention.py: db.get_pending_tasks_summary(user_id)
  → prompts.py: build_system_prompt(tool_hints, memory_summary, task_summary)
  → System prompt includes "## Pending Tasks" section
  → AI sees pending tasks and can reference them proactively
```

### 7.3 Notification Reply (F-03)

```
Bot (email monitor): "New email from John: Meeting tomorrow at 3pm..."
  ↓
User replies to this message: "translate to Chinese"
  → discord/client.py: detect message.reference → fetch referenced message
  → Referenced message is from bot → extract content
  → on_mention(content="translate to Chinese", ..., referenced_content="New email from John...")
  → mention.py: inject "[Referenced bot message]\n..." into user prompt
  → AI sees both the email content and the instruction → translates
```

## 8. Shared Modules & Reuse Strategy

| Shared Component                          | Used By                    | How                                                        |
|:------------------------------------------|:---------------------------|:-----------------------------------------------------------|
| `memory/database.py` (Database class)     | tool/task, core/mention.py | Extended with task CRUD. Same instance injected at startup |
| `config/prompts.py` (build_system_prompt) | core/mention.py            | Extended with task_summary parameter                       |
| `tool.db` injection pattern               | handler.py → all tools     | Task tool gets db the same way as memo/reminder            |
| `_load_json` / `_save_json` helpers       | database.py internally     | Reused for tasks.json, no new I/O code                     |

## 9. Risks & Notes

| Risk                                                | Mitigation                                                                                  |
|:----------------------------------------------------|:--------------------------------------------------------------------------------------------|
| MentionHandler signature change (5→6 params)        | Only two implementations: discord client and mention.py. Both updated together              |
| Referenced message fetch may fail (deleted message) | Wrap in try/except, fall back to no reference context                                       |
| Task context makes system prompt longer             | Hard cap at 1000 chars. Only pending tasks injected (completed excluded)                    |
| AI creates tasks for every request                  | BEHAVIOR_STRATEGY explicitly instructs: "only when user explicitly asks to track something" |
| Too many pending tasks                              | Default list caps at 20. Summary injection also capped                                      |

## 10. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version | ALL            | -      |
