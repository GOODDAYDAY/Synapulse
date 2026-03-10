# REQ-002 Memory Layer & Core Tool Expansion

> Status: Completed
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Background

Synapulse has a clean architecture (dynamic loading, IoC, provider abstraction, token compression), but its actual
personal assistant capabilities are nearly empty:

- **No memory**: Each @mention is fully independent. Discord history fetches only 5 messages and is not persisted. All
  state is lost on restart. The assistant cannot maintain continuity across conversations.
- **Too few tools**: Only `brave_search` (web search) and `local_files` (file browsing) exist. Basic personal assistant
  needs (notes, reminders, knowledge recall) are completely unsupported.
- The system prompt claims capabilities (scheduling, reminders, writing) that have no tool backing, creating an
  experience gap.

This requirement adds a persistent memory layer and essential personal assistant tools to transform Synapulse from an "
architecture demo" into a functional assistant.

## 2. Target Users & Scenarios

- **User**: Project author (single-user personal assistant)
- **Scenarios**:
    - Continuous conversation: cross-message context continuity ("what I just said...")
    - Personal notes: ask the assistant to remember things, recall them later
    - Timed reminders: "remind me in 5 minutes to join the meeting"
    - Personalized answers: combine search + memory for context-aware responses
    - Daily Q&A: search, knowledge, translation

## 3. Functional Requirements

### F-01 Conversation History Persistence

- **Main flow**:
    - After each mention is handled, persist the conversation turn (user message + AI reply + tool call summary) to
      local storage
    - On next mention, load the user's recent conversation history from storage and inject into context
    - Storage is isolated by `user_id` (single user now, field reserved for future)
    - Storage is separated by `channel_id` (different channels = different conversation threads)
    - Storage format: JSON files in a local directory, path configurable via `DATABASE_PATH` in `.env`
    - Storage directory excluded from git via `.gitignore`
- **Error handling**:
    - Storage read/write failure → graceful degradation to memoryless mode, current conversation unaffected
    - Log storage exceptions at WARNING level
- **Edge cases**:
    - History too long → auto-truncate to fit token budget before injection
    - User can clear their conversation history via command (see F-06)

### F-02 Long-term Memory Summarization

- **Main flow**:
    - When conversation history exceeds threshold (e.g., 20 turns), use AI to compress older conversations into a
      summary
    - Summary stored as a separate record, subsequent conversations inject summary instead of raw history
    - Summary includes: key topics discussed, user preferences discovered, important conclusions
    - Summarization uses the existing `provider.chat()` — no new AI dependency
- **Error handling**:
    - Summarization failure → fall back to truncation (keep most recent N turns, drop oldest)
- **Edge cases**:
    - Cascading summarization: summary + new conversations → re-summarize without losing key info
    - Summary has a token budget cap (configurable, default ~500 tokens)

### F-03 Memo Tool (Notes/Knowledge Base)

- **Main flow**:
    - New AI tool `memo` with actions: `save`, `list`, `search`, `delete`
    - User says "remember: my server IP is xxx" → AI calls `memo.save`
    - User says "what's my server IP?" → AI calls `memo.search`, finds and answers
    - Persistent storage (JSON files), survives restart
    - Each memo entry: `id`, `user_id`, `content`, `created_at`, `updated_at`
- **Error handling**:
    - Storage full → inform user to clean up old entries
    - Duplicate detection: warn if very similar memo already exists
- **Edge cases**:
    - Fuzzy search: keyword matching against memo content
    - Sorted by recency (newest first)
    - Reasonable entry limit (e.g., 1000 memos per user)

### F-04 Reminder Tool

- **Main flow**:
    - New AI tool `reminder` with actions: `create`, `list`, `cancel`
    - User says "remind me in 5 minutes to drink water" → AI calls `reminder.create`
    - AI parses natural language time into absolute timestamp (AI does the parsing, tool receives timestamp)
    - At trigger time, send reminder message to the originating channel via `channel.send`
    - Persistent storage (JSON files), restart recovers unfired reminders
- **Error handling**:
    - Invalid timestamp → return error to AI for re-interpretation
    - After restart, check for overdue reminders: fire immediately with "[Delayed]" tag
- **Edge cases**:
    - Support absolute time ("tomorrow 3pm") and relative time ("in 2 hours") — AI resolves to ISO timestamp
    - Support recurring reminders (daily, weekly) — stored as cron expression
    - Reminder includes original message context for clarity
    - Cancel by ID or by description search

### F-05 System Prompt Enhancement

- **Main flow**:
    - Inject user's long-term memory summary into system prompt context section
    - Update Capabilities section to reflect actual tool availability (remove unsupported claims)
    - Add behavioral strategy section:
        - When to use tools vs. answer directly
        - How to decompose multi-step tasks
        - How to handle errors and retry
    - Memory summary injection has a token budget cap
- **Edge cases**:
    - No memory summary yet → omit the section, don't inject empty content
    - Summary too long → truncate to budget

### F-06 Conversation History Management Command

- **Main flow**:
    - User can say "clear my history" / "forget everything" → AI recognizes intent
    - AI confirms before clearing: "Are you sure you want to clear all conversation history?"
    - After confirmation, clear conversation history for that user+channel
    - Memos are NOT cleared (they are explicit saves, not conversation history)
- **Edge cases**:
    - Confirmation mechanism: AI asks, user confirms, then clear
    - Partial clear: "forget what I said today" → clear only today's entries

## 4. Non-functional Requirements

- **Storage**: JSON files (stdlib `json` + `pathlib`, zero external dependency). One file per data type under a
  configurable directory via `DATABASE_PATH` in `.env`, default `data/synapulse.db` (directory derived from path)
- **Data safety**: Storage directory added to `.gitignore`. No sensitive info in memory summaries (AI instructed to
  exclude passwords/tokens)
- **Performance**: Memory loading < 100ms per request. JSON file I/O is more than sufficient for single-user workload
- **Architecture consistency**:
    - New tools follow `tool/{name}/handler.py` + inherit `OpenAITool, AnthropicTool`
    - Memory layer is an independent module under `apps/bot/memory/` — core injects via callback, no dependency
      direction violation
    - Zero new external dependencies — uses only Python stdlib
- **Recoverability**: All persistent data auto-recovers on restart. JSON files are human-readable and trivially
  recoverable

## 5. Out of Scope

- Multi-user permission management (reserve `user_id` field only)
- Calendar / scheduling integration (requires external API, future requirement)
- Weather query tool (requires new API key, future requirement)
- Voice / image processing
- LangGraph / Multi-Agent architecture refactoring
- Web UI management interface
- End-to-end encryption of stored data

## 6. Acceptance Criteria

| ID    | Feature | Condition                                                                          | Expected Result                                                           |
|:------|:--------|:-----------------------------------------------------------------------------------|:--------------------------------------------------------------------------|
| AC-01 | F-01    | User sends 2 consecutive messages, 2nd references content from 1st                 | AI understands context and answers correctly                              |
| AC-02 | F-01    | Restart bot, user mentions previous conversation                                   | AI recovers from persistent storage and answers                           |
| AC-03 | F-02    | After 20+ turns of conversation, continue chatting                                 | AI still remembers key early information via summary                      |
| AC-04 | F-03    | User says "remember my birthday is January 1st", later asks "when is my birthday?" | AI saves and correctly recalls                                            |
| AC-05 | F-03    | Restart bot, ask the same question                                                 | Memo data not lost                                                        |
| AC-06 | F-04    | User says "remind me in 5 minutes to drink water"                                  | Channel receives reminder message after 5 minutes                         |
| AC-07 | F-04    | Set a reminder then restart bot                                                    | Reminder still fires on time after restart                                |
| AC-08 | F-05    | Inspect system prompt sent to AI                                                   | Contains user memory summary and accurate capability description          |
| AC-09 | F-06    | User says "clear my conversation history"                                          | AI confirms, clears history; subsequent conversation has no prior context |

## 7. Change Log

| Version | Date       | Changes                                                      | Affected Scope              | Reason                                               |
|:--------|:-----------|:-------------------------------------------------------------|:----------------------------|:-----------------------------------------------------|
| v1      | 2026-03-10 | Initial version                                              | ALL                         | -                                                    |
| v2      | 2026-03-10 | Storage changed from SQLite/aiosqlite to JSON files (stdlib) | F-01, F-03, F-04, Section 4 | Simplify: zero external deps, human-readable storage |
