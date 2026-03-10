# REQ-001 Discord AI Bot

> Status: Completed
> Created: 2025-02-09
> Updated: 2026-03-10

## 1. Background

A personal AI assistant running on Discord that can:

- Chat with AI via @mention, with multi-turn context support
- Call tools (web search, file browsing, etc.) to complete complex tasks
- Monitor email inboxes in the background, classify and summarize new emails with AI, and push notifications to a
  Discord channel
- Support multiple AI providers, switchable on demand without code changes

Pain point: existing solutions are either too simple (chat only) or overly complex (enterprise frameworks). A
lightweight yet extensible personal assistant is needed.

## 2. Target Users & Scenarios

- **Target users**: Individual developers / technical users
- **Scenarios**:
    - @mention the bot in Discord to ask questions and receive AI-generated replies
    - AI automatically calls tools to search the web, browse local files, etc.
    - Background monitoring of Gmail / Outlook / QQ Mail with automatic summary notifications for new emails
    - Hot-reload job scheduling by editing a JSON config file, no restart required

## 3. Functional Requirements

### F-01 AI Chat via Discord

- Main flow: User @mentions the bot in a Discord channel → bot reads the last 5 messages as context → calls AI to
  generate a reply → sends the reply
- Error handling: AI call failures return a user-readable error message, never throw unhandled exceptions
- Edge cases:
    - Messages exceeding Discord's 2000-character limit are automatically split into multiple sends
    - The bot's own messages do not trigger replies (prevents self-loop)
    - The bot adds a 🙋‍♀️ emoji reaction to @mentions to acknowledge receipt

### F-02 Multi-Provider AI Support

- Main flow: Specify the provider via `AI_PROVIDER` in `.env` → dynamically load the corresponding module at startup →
  auto-authenticate
- Supported providers:
    - `mock` — For testing, returns fixed text
    - `copilot` — GitHub Models API (OpenAI-compatible), supports OAuth Device Flow authentication
    - `ollama` — Local Ollama (OpenAI-compatible), no authentication required
- Error handling: Missing required configuration raises an error at startup, not on first call
- Edge cases: Provider authentication failure provides clear guidance messages

### F-03 Tool Calling

- Main flow: AI response contains tool_call → validate arguments (JSON Schema) → execute tool → return result to AI → AI
  continues reasoning or generates final reply
- Multi-round loop: Up to 10 rounds, 1-second interval between rounds (rate-limit protection)
- Implemented tools:
    - `brave_search` — Search the web using Brave Search API, returns top 5 results
    - `local_files` — Securely browse the local file system (restricted to allowed directories), supports listing
      directories, reading files, and searching
- Token management: Compress consumed tool results after each round, only keep the latest round's results in full
- Error handling: Argument validation failure → structured error returned to AI for self-correction; unknown tool name →
  error message returned to AI
- Edge cases: Returns a friendly message when max rounds are reached, never loops infinitely

### F-04 Tool Auto-Discovery

- Main flow: Scan all subdirectories under `tool/` at startup → import the `Tool` class from `handler.py` →
  auto-register
- Each tool carries a `usage_hint` → automatically assembled into the system prompt at startup
- Adding a new tool requires only a new directory + handler.py, no configuration or code changes needed

### F-05 Email Monitoring Jobs

- Main flow: Background scheduled task → fetch unread emails via IMAP → AI classifies and summarizes (distinguishes
  important emails from ads) → push to Discord channel
- Supported mailboxes: Gmail, Outlook, QQ Mail
- Deduplication: Generate a unique key from `sender|subject|date`, keep the last 500 records in memory
- Ad filtering: AI outputs `SKIP` for ads/spam, no notification sent
- Error handling: IMAP connection failure → log and wait for the next cycle to retry
- Edge cases:
    - First run only fetches emails from the last 2 days, prevents full mailbox pull
    - Maximum 20 emails per fetch, prevents mailbox explosion

### F-06 Job Auto-Discovery & Hot-Reload

- Main flow: Scan all subdirectories under `job/` at startup → import the `Job` class from `handler.py` → auto-register
- Hot-reload: `jobs.json` is re-read every tick, changes take effect on the next tick without restart
- Configuration fields: enabled (toggle), schedule (cron expression), notify_channel (target channel), prompt (AI
  prompt)
- Guard: Disabled / validation failure / no channel → retry every 60 seconds

### F-07 Dynamic Channel Support

- Main flow: Specify the channel via `CHANNEL_TYPE` in `.env` → dynamically load at startup
- Current implementation: Discord (discord.py)
- Channel receives the `on_mention` handler via callback, no direct dependency on core

## 4. Non-functional Requirements

- **Extensibility**: Adding a new provider / channel / tool / job requires only a new directory, zero configuration
- **Startup speed**: Configuration validation completes at startup, fail-fast
- **Token efficiency**: Compress historical results in multi-round tool-call loops, reducing a 5-round browsing session
  from 30-50K tokens to under 5K
- **Security**:
    - Sensitive configuration only via `.env`, automatically masked in logs
    - `local_files` tool restricted to allowed paths, rejects unauthorized access
- **Reliability**: Errors at all layers are caught and converted to user-readable messages, a single failure never
  causes service interruption
- **Logging**: Tiered logging (console INFO + file DEBUG), 5MB rotation, 3 backups

## 5. Out of Scope

- Web dashboard (planned, not implemented)
- Multi-server / multi-user permission management
- Database persistence (currently all in-memory)
- Anthropic native API provider (base class implemented, no concrete provider)
- Voice / video features

## 6. Acceptance Criteria

| ID    | Feature | Condition                              | Expected Result                                  |
|:------|:--------|:---------------------------------------|:-------------------------------------------------|
| AC-01 | F-01    | @mention bot in Discord                | Bot replies with AI-generated text               |
| AC-02 | F-01    | Reply exceeds 2000 chars               | Message split into multiple sends                |
| AC-03 | F-02    | Set AI_PROVIDER=mock                   | Bot replies "mock hello"                         |
| AC-04 | F-02    | Set AI_PROVIDER=copilot, valid token   | Bot replies via GitHub Models API                |
| AC-05 | F-02    | Set AI_PROVIDER=ollama, Ollama running | Bot replies via local Ollama                     |
| AC-06 | F-03    | User asks to search the web            | AI calls brave_search tool, returns results      |
| AC-07 | F-03    | Tool call with invalid args            | Error returned to AI, AI retries with valid args |
| AC-08 | F-03    | 10 tool rounds reached                 | Bot returns max-rounds message, no infinite loop |
| AC-09 | F-04    | Add new tool directory with handler.py | Tool auto-discovered at next startup             |
| AC-10 | F-05    | New unread email arrives in Gmail      | Summary notification sent to Discord channel     |
| AC-11 | F-05    | Email is ad/spam                       | AI returns SKIP, no notification sent            |
| AC-12 | F-05    | Same email fetched twice               | Dedup prevents duplicate notification            |
| AC-13 | F-06    | Edit jobs.json to disable a job        | Job stops on next tick, no restart needed        |
| AC-14 | F-06    | Edit jobs.json to change schedule      | New schedule takes effect on next tick           |
| AC-15 | F-07    | Set CHANNEL_TYPE=discord               | Bot connects to Discord via discord.py           |

## 7. Change Log

| Version | Date       | Changes                                                    | Affected Scope | Reason |
|:--------|:-----------|:-----------------------------------------------------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version (retroactive from existing implementation) | ALL            | -      |
