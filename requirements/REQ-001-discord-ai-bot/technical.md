# REQ-001 Technical Design

> Status: Completed
> Requirement: requirement.md
> Created: 2025-02-09
> Updated: 2026-03-10

## 1. Technology Stack

| Module     | Technology       | Rationale                                             |
|:-----------|:-----------------|:------------------------------------------------------|
| Runtime    | Python 3.11+     | Union type syntax, asyncio maturity, rich ecosystem   |
| Channel    | discord.py       | Mature Discord library, native async support          |
| AI API     | aiohttp          | Async HTTP client, direct API calls without heavy SDK |
| Email      | imaplib (stdlib) | IMAP protocol, no external dependency                 |
| Scheduling | croniter         | Lightweight cron expression parser                    |
| Validation | jsonschema       | Tool argument validation against JSON Schema          |
| Config     | python-dotenv    | .env file loading, industry standard                  |
| Logging    | logging (stdlib) | dictConfig, RotatingFileHandler                       |

## 2. Design Principles

- **High cohesion, low coupling**: Each layer has one responsibility; layers communicate via callbacks, never import
  each other
- **Inversion of control**: Core injects callbacks into passive layers; passive layers never depend back on core
- **Convention over configuration**: Dynamic loading based on directory name + conventional class name; no registry, no
  match-case
- **Self-validating implementations**: Each implementation validates its own config; config only loads, never decides
- **Token-conscious orchestration**: Compress consumed results in multi-round tool loops to control token cost
- **Code does mechanics, AI does decisions**: Code handles traversal/formatting; AI handles matching/judgment

## 3. Architecture Overview

```
apps/bot/
├── main.py                         # Entry point
├── config/                         # Settings, prompts, logging, job config
│   ├── settings.py                 # Frozen dataclass, loads .env
│   ├── prompts.py                  # SYSTEM_PROMPT, TOOLS_GUIDANCE
│   ├── logging.py                  # dictConfig setup
│   ├── jobs.py                     # Hot-reload jobs.json reader
│   └── jobs.json                   # Runtime job config (hot-reloadable)
├── core/                           # Orchestration layer
│   ├── handler.py                  # Bootstrap: wire provider → tools → jobs → channel
│   ├── loader.py                   # Dynamic discovery: scan_tools(), scan_jobs()
│   └── mention.py                  # Tool-call loop: make_mention_handler()
├── channel/                        # Platform I/O (passive)
│   ├── base.py                     # BaseChannel ABC
│   └── discord/client.py           # Channel(BaseChannel)
├── provider/                       # AI API adapters (passive)
│   ├── base.py                     # BaseProvider, OpenAIProvider, AnthropicProvider
│   ├── copilot/                    # Provider(OpenAIProvider) + OAuth auth
│   │   ├── chat.py
│   │   └── auth.py
│   ├── mock/chat.py                # Provider(BaseProvider) — testing
│   └── ollama/chat.py              # Provider(OpenAIProvider)
├── tool/                           # Capabilities (passive)
│   ├── base.py                     # BaseTool, OpenAITool, AnthropicTool
│   ├── brave_search/handler.py     # Tool(OpenAITool, AnthropicTool)
│   └── local_files/handler.py      # Tool(OpenAITool, AnthropicTool)
└── job/                            # Background tasks (passive)
    ├── base.py                     # BaseJob ABC
    ├── cron.py                     # CronJob(BaseJob) — scheduled loop
    ├── listen.py                   # ListenJob(BaseJob) — continuous listener
    ├── _imap.py                    # EmailCronJob(CronJob) — shared email base
    ├── gmail/handler.py            # Job(EmailCronJob)
    ├── outlook/handler.py          # Job(EmailCronJob)
    └── qqmail/handler.py           # Job(EmailCronJob)
```

See `tech-architecture.puml` for component diagram.

## 4. Module Design

### 4.1 Config Layer (`config/`)

- **Responsibility**: Load environment variables, provide system prompts, configure logging, read job config
- **Public interface**:
    - `config` — Frozen dataclass singleton, all modules read configuration through it
    - `config.log_summary()` — Print config summary at startup (sensitive values masked)
    - `SYSTEM_PROMPT`, `TOOLS_GUIDANCE` — Prompt constants
    - `setup_logging(level)` — Initialize logging system
    - `load_job_config(name)` — Read job config by name from jobs.json (re-reads file every call)
- **Reuse notes**: The only package shared across all layers; all other layers may import config

### 4.2 Core Layer (`core/`)

- **Responsibility**: Lifecycle orchestration — loading, wiring, startup, runtime loop
- **Public interface**:
    - `start()` — Entry point, complete bootstrap sequence
    - `make_mention_handler(provider, tools, send_file)` — Factory function, returns mention callback
    - `scan_tools()` → `dict[str, BaseTool]`
    - `scan_jobs()` → `list[BaseJob]`
    - `format_tools_for_provider(tools, api_format)` → `list[dict]`
    - `format_tool_hints(tools)` → `str`
- **Internal structure**:
    - `handler.py` — Bootstrap orchestration (config → provider → tools → jobs → channel)
    - `loader.py` — Filesystem scanning + importlib dynamic loading
    - `mention.py` — Tool-call loop (up to 10 rounds, with argument validation, result compression, rate limiting)

### 4.3 Channel Layer (`channel/`)

- **Responsibility**: Platform I/O — receive messages, send replies
- **Public interface (ABC)**:
    - `validate()` — Validate channel-specific config
    - `run(on_mention)` — Start listening, call the callback on @mention
    - `wait_until_ready()` — Block until the connection is ready
    - `send(channel_id, message)` — Send a text message
    - `send_file(channel_id, file_path, comment)` — Send a file
- **Discord implementation**:
    - Auto-split messages exceeding 2000 characters
    - Add 🙋‍♀️ reaction on @mention
    - Read the last 5 messages as context history

### 4.4 Provider Layer (`provider/`)

- **Responsibility**: AI API adaptation — message formatting, tool call parsing, result compression
- **Public interface (ABC)**:
    - `authenticate()` — Authenticate (optional)
    - `build_messages(system_prompt, user_prompt)` → `list`
    - `chat(messages, tool_choice)` → `ChatResponse`
    - `append_tool_result(messages, tool_call, result)`
    - `parse_tool_calls(raw_msg)` → `list[ToolCall]`
    - `compress_tool_results(messages, threshold)`
- **Internal structure**: Symmetric hierarchy
    - `BaseProvider` → `OpenAIProvider` (openai format) / `AnthropicProvider` (anthropic format)
    - Concrete implementations inherit from the matching format class, only need to implement `chat()` and
      `authenticate()`
- **Reuse notes**: OpenAIProvider is shared by copilot and ollama

### 4.5 Tool Layer (`tool/`)

- **Responsibility**: Capability extension — web search, file browsing, etc.
- **Public interface (ABC)**:
    - `validate()` — Validate tool-specific config (e.g., API key)
    - `execute(**kwargs)` → `str`
    - `to_openai()` / `to_anthropic()` → `dict` — Format as tool definition for the corresponding API
- **Internal structure**: Mixin hierarchy
    - `BaseTool` → `OpenAITool` / `AnthropicTool` (format mixins)
    - Concrete tools inherit from both mixins via multiple inheritance to support all API formats
- **Per-tool routing**: Each tool carries a `usage_hint`, automatically assembled into the system prompt at startup

### 4.6 Job Layer (`job/`)

- **Responsibility**: Background tasks — scheduled fetching, continuous listening, AI summarization, push notifications
- **Public interface (ABC)**:
    - `validate()` — Validate job-specific config (e.g., IMAP credentials)
    - `start(notify)` — Start the job loop
    - `process(item, prompt)` → `str` — Process a single item
    - `format_for_ai(item)` → `str` — Format as AI input
    - `format_notification(item, summary)` → `str` — Format as notification message
- **Internal structure**: Three-level inheritance
    - `BaseJob` → `CronJob` (scheduled) / `ListenJob` (continuous listener)
    - `CronJob` → `EmailCronJob` (shared email monitoring base with dedup, ad filtering, AI classification)
    - Concrete email jobs only need to implement `name`, `validate()`, and `fetch()`
- **Reuse notes**: EmailCronJob is shared by gmail, outlook, and qqmail

## 5. Data Model

```
ToolCall
├── id: str              # Call ID from AI response
├── name: str            # Tool name
└── arguments: dict      # Parsed JSON arguments

ChatResponse
├── text: str | None     # Final text (mutually exclusive with tool_calls)
└── tool_calls: list[ToolCall]

Config (frozen dataclass)
├── CHANNEL_TYPE: str
├── DISCORD_TOKEN: str
├── AI_PROVIDER: str
├── AI_MODEL: str
├── GITHUB_TOKEN / GITHUB_CLIENT_ID: str
├── OLLAMA_BASE_URL: str
├── BRAVE_API_KEY: str
├── LOCAL_FILES_ALLOWED_PATHS: str
├── GMAIL_ADDRESS / GMAIL_APP_PASSWORD: str
├── OUTLOOK_ADDRESS / OUTLOOK_APP_PASSWORD: str
├── QQ_MAIL_ADDRESS / QQ_MAIL_AUTH_CODE: str
└── LOG_LEVEL: str
```

## 6. API Design

No external API. This system is a Discord bot + background tasks. All interactions go through:

- **Discord Gateway**: WebSocket for receiving messages and sending replies
- **AI Provider HTTP API**: aiohttp calls to GitHub Models / Ollama
- **IMAP**: imaplib connections to email servers

## 7. Key Flows

### 7.1 Mention Handling (Tool-Call Loop)

```
User @mention bot
       ↓
Discord Channel: on_message → on_mention(content, channel_id, history)
       ↓
mention.handle_mention:
  1. build_messages(system_prompt, user_prompt + history)
  2. loop (max 10 rounds):
     provider.chat(messages) → ChatResponse
     ├── if text: return text (done)
     └── if tool_calls:
         for each call:
           validate(args, tool.parameters)  ← JSON Schema
           tool.execute(**args) → result
           append_tool_result(messages, call, result)
         compress_tool_results(messages)    ← shrink consumed results
         sleep(1s)                          ← rate-limit protection
  3. return final text or max-rounds message
       ↓
Discord Channel: send reply (auto-split if > 2000 chars)
```

See `tech-seq-mention.puml` for sequence diagram.

### 7.2 Email Monitoring Job

```
CronJob.start(notify):
  loop:
    cfg = load_job_config(name)        ← hot-reload
    guard: disabled → sleep 60s
    guard: validation fail → sleep 60s
    guard: no notify_channel → sleep 60s
    wait until next cron time
    items = fetch()                    ← IMAP: UNSEEN + SINCE 2 days
    for each item:
      key = sender|subject|date
      if duplicate: skip
      text = format_for_ai(item)
      summary = summarize(prompt, text) ← AI classification
      if SKIP: skip (ad/spam)
      record(key)                       ← dedup
      message = format_notification(item, summary)
      notify(channel_id, message)       ← Discord send
```

### 7.3 Bootstrap Sequence

```
main.py → core/handler.start():
  1. setup_logging() + config.log_summary()
  2. importlib: load provider → Provider() → authenticate()
  3. scan_tools() → validate() each → format for provider → set provider.tools
  4. scan_jobs() → inject summarize callback into each
  5. importlib: load channel → Channel() → validate()
  6. channel.run(on_mention=make_mention_handler(provider, tools))
  7. job.start(channel.send) for each job (background tasks)
  8. await channel task (blocks until shutdown)
```

## 8. Shared Modules & Reuse Strategy

| Shared Module                               | Used By                | Purpose                                             |
|:--------------------------------------------|:-----------------------|:----------------------------------------------------|
| `config/settings.py`                        | All layers             | Environment variables, frozen config singleton      |
| `config/prompts.py`                         | core/mention           | System prompt, tool-use preamble                    |
| `config/jobs.py`                            | job/cron, job/listen   | Hot-reloadable job config reader                    |
| `provider/base.py` (OpenAIProvider)         | copilot, ollama        | OpenAI-compatible message formatting                |
| `provider/base.py` (AnthropicProvider)      | (future providers)     | Anthropic message formatting                        |
| `tool/base.py` (OpenAITool + AnthropicTool) | All tools              | Multi-format tool definition mixins                 |
| `job/_imap.py` (EmailCronJob)               | gmail, outlook, qqmail | Email fetch, dedup, ad filtering, AI classification |
| `job/cron.py` (CronJob)                     | All cron-based jobs    | Schedule loop, hot-reload, guard clauses            |
| `job/listen.py` (ListenJob)                 | (future listener jobs) | Continuous listener loop                            |

## 9. Risks & Notes

- **No persistence**: Email dedup history is in-memory only, lost on restart. Acceptable for a personal assistant;
  scaling up requires a database
- **Single process**: All tasks run in the same asyncio event loop. A blocking task affects everything. No issue at
  current load
- **IMAP polling**: Minimum polling interval is 5 minutes, not real-time. Real-time requires IMAP IDLE or push
  notifications
- **Token cost**: Token consumption in multi-round tool-call loops grows linearly with rounds; mitigated by compression
  but not fully eliminated
- **Discord rate limit**: 1-second sleep provides basic protection; may be insufficient under high concurrency

## 10. Change Log

| Version | Date       | Changes                                                    | Affected Scope | Reason |
|:--------|:-----------|:-----------------------------------------------------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version (retroactive from existing implementation) | ALL            | -      |
