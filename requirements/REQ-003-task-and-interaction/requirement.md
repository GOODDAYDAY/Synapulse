# REQ-003 Task Management & Notification Interaction

> Status: Requirement Finalized
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Background

REQ-002 delivered the memory layer and core tools (memo, reminder), giving Synapulse persistent conversation memory and
basic personal assistant capabilities. However, two significant gaps remain:

- **No task management**: The user has no way to track multi-step to-dos across messages. Saying "help me remember to do
  X" can only be approximated with the memo tool, which has no concept of status (todo/in-progress/done), priority, or
  due dates. A personal assistant without a task list is incomplete.
- **Job notifications are one-way**: Background jobs (email monitors) push notifications to Discord channels, but the
  user cannot reply to a notification and have the bot understand the context. For example, when the email monitor posts
  a summary, replying "summarize this in English" has no way to reference the original notification content.

This requirement adds a task management tool and makes job notifications interactive, completing the personal
assistant's core capability set.

## 2. Target Users & Scenarios

- **User**: Project author (single-user personal assistant)
- **Scenarios**:
    - Task tracking: "add a task: submit report by Friday" → track until done
    - Task review: "what do I need to do today?" → list pending tasks with due dates
    - Task lifecycle: create → update status → mark complete → delete
    - Proactive awareness: AI mentions upcoming deadlines in relevant conversations
    - Notification interaction: email monitor posts a summary → user replies "translate this to English" → AI sees the
      original notification and responds in context

## 3. Functional Requirements

### F-01 Task Management Tool

- **Main flow**:
    - New AI tool `task` with actions: `create`, `list`, `update`, `complete`, `delete`
    - Each task record: `id`, `user_id`, `title`, `description` (optional), `status` (todo/in_progress/done),
      `priority` (low/medium/high), `due_date` (optional, ISO 8601), `created_at`, `updated_at`
    - `create(title, description?, priority?, due_date?)` → creates task with status=todo
    - `list(status?, priority?)` → returns filtered task list, sorted by priority then due_date
    - `update(task_id, title?, description?, status?, priority?, due_date?)` → updates specified fields
    - `complete(task_id)` → shorthand for setting status=done
    - `delete(task_id)` → permanently removes the task
    - Persistent storage via JSON files, reusing the existing `Database` class
- **Error handling**:
    - Task not found → return clear error string to AI
    - Invalid status/priority values → return error with valid options
    - Storage failure → graceful degradation, log warning
- **Edge cases**:
    - Task limit: 500 tasks per user (prevent unbounded growth)
    - Duplicate detection: warn if a task with very similar title already exists (case-insensitive comparison)
    - Listing with no tasks → return "No tasks found" message
    - Completed tasks are still listed when explicitly filtered, but hidden from default list

### F-02 Task Context Injection

- **Main flow**:
    - Before each AI call, load the user's pending tasks (status != done)
    - Generate a compact task summary and inject into the system prompt context
    - AI can proactively mention relevant tasks (e.g., user asks "what should I do today?" → AI references pending tasks
      with today's due date)
    - Task summary format: compact list with id, title, priority, due_date
- **Error handling**:
    - Task loading failure → omit task section from prompt, log warning
- **Edge cases**:
    - No pending tasks → omit task section entirely (don't inject empty content)
    - Too many pending tasks → cap at most recent/highest priority 20 tasks
    - Task summary has a token budget cap (configurable, default ~1000 chars)

### F-03 Job Notification Interaction

- **Main flow**:
    - When a user replies to a bot message (Discord message reference), extract the original bot message content
    - Inject the referenced message as additional context in the mention handler:
      `[Referenced bot message]\n<original content>`
    - The AI sees both the original notification and the user's follow-up instruction
    - Works for any bot message (job notifications, previous AI replies, etc.)
- **Error handling**:
    - Referenced message not found or not from the bot → ignore, process as normal mention
    - Referenced message too long → truncate to a reasonable limit (e.g., 2000 chars)
- **Edge cases**:
    - User replies to a very old bot message → still works (content is fetched from Discord)
    - User replies to a message in a different channel → not supported (Discord doesn't allow this)
    - Nested replies (reply to a reply) → only include the directly referenced message

## 4. Non-functional Requirements

- **Storage**: JSON files (stdlib `json` + `pathlib`), extending the existing `Database` class with a new `tasks.json`
  file. Zero new external dependencies
- **Architecture consistency**:
    - Task tool follows `tool/task/handler.py`, inherits `OpenAITool, AnthropicTool`
    - Dynamic loading via existing `scan_tools()` — no loader changes needed
    - Database injection via existing `tool.db` pattern
    - Task context injection follows the same pattern as memory summary injection
- **Performance**: Task loading < 100ms. JSON file I/O sufficient for single-user workload
- **Data safety**: Storage directory already in `.gitignore` (from REQ-002)

## 5. Out of Scope

- Calendar / Google Calendar integration (requires external API)
- Task dependencies or subtasks (Gantt-chart level complexity)
- Task auto-completion or timeout-based status changes
- Task sharing between users (single-user only)
- Rich notification formatting (embeds, buttons) — plain text sufficient
- Two-way email reply (composing and sending emails)

## 6. Acceptance Criteria

| ID    | Feature | Condition                                                              | Expected Result                                                  |
|:------|:--------|:-----------------------------------------------------------------------|:-----------------------------------------------------------------|
| AC-01 | F-01    | User says "add a task: submit report by Friday, high priority"         | AI creates task with title, due_date, priority=high, returns #id |
| AC-02 | F-01    | User says "what are my tasks?"                                         | AI lists all pending tasks sorted by priority and due date       |
| AC-03 | F-01    | User says "mark task 3 as done"                                        | AI updates task #3 status to done                                |
| AC-04 | F-01    | User says "delete task 5"                                              | AI permanently removes task #5                                   |
| AC-05 | F-01    | Restart bot, query tasks                                               | Task data persists across restarts                               |
| AC-06 | F-02    | User has pending tasks with today's due date, asks "what should I do?" | AI references the due tasks in its response                      |
| AC-07 | F-02    | User has no pending tasks                                              | No task section appears in AI context                            |
| AC-08 | F-03    | Email monitor posts notification, user replies "summarize in English"  | AI sees original notification content and summarizes it          |
| AC-09 | F-03    | User replies to bot's previous answer "elaborate on that"              | AI sees its previous answer and elaborates                       |

## 7. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version | ALL            | -      |
