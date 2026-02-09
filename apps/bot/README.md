# Bot

The core bot application of Synapulse.

## Architecture

```
channel/*  ──→  core/handler  ──→  provider/*
  (I/O)        (orchestrate)      (AI adapter)
                    ↕                  ↑
                  tool/*            job/*
               (capabilities)   (background)
```

High cohesion, low coupling. Each layer has one job:

- **core/** — THE orchestrator. Loads channel, provider, and tools. Injects callbacks, orchestrates the tool-call loop.
  All coordination lives here.
- **channel/** — Platform I/O only. Receives a callback and calls it. Knows nothing about providers or tools.
- **provider/** — AI API adapter. Formats messages for a specific LLM API. Knows nothing about channels or tools.
- **tool/** — Capabilities (search, etc.). Each tool defines itself and formats its definition for different APIs. Knows
  nothing about other layers.
- **job/** — Background tasks (monitoring, listeners). Each job fetches data, asks the AI to summarize, and notifies a
  channel. Knows nothing about other layers — receives `notify` callback from core, `summarize` set as attribute.
- **config/** — Settings, logging, prompts, and job config. Shared by all layers. Secrets in `.env`, operational job
  config in `config/jobs.json` (hot-reloadable).

## Directory Structure

```
bot/
├── main.py                         # Bootstrap: logging → core.start()
├── requirements.txt
├── config/
│   ├── settings.py                 # Frozen dataclass, secret masking
│   ├── logging.py                  # dictConfig with console + rotating file
│   ├── prompts.py                  # Static system prompt
│   ├── jobs.json                   # Hot-reloadable job config (schedule, channel, prompt)
│   ├── jobs.py                     # load_job_config() — re-reads JSON each call
│   └── logs/                       # Log files (git-ignored)
├── core/
│   ├── handler.py                  # Bootstrap: config → provider → tools → jobs → channel
│   ├── loader.py                   # Dynamic discovery: scan_tools(), scan_jobs()
│   └── mention.py                  # Tool-call loop: make_mention_handler()
├── provider/
│   ├── base.py                     # BaseProvider, OpenAIProvider, AnthropicProvider
│   ├── mock/
│   │   └── chat.py                 # Returns "mock hello" (for testing)
│   ├── copilot/
│   │   ├── chat.py                 # GitHub Models API (OpenAI-compatible)
│   │   └── auth.py                 # .env / OAuth Device Flow, auto-save to .env
│   └── ollama/
│       └── chat.py                 # Local Ollama (OpenAI-compatible)
├── channel/
│   ├── base.py                     # BaseChannel ABC (validate + run)
│   └── discord/
│       └── client.py               # Discord event listener & reply
├── tool/
│   ├── base.py                     # BaseTool, OpenAITool, AnthropicTool
│   └── brave_search/
│       └── handler.py              # Brave Search API
└── job/
    ├── base.py                     # BaseJob ABC (validate, format, start)
    ├── cron.py                     # CronJob(BaseJob) — interval-based scheduling
    ├── listen.py                   # ListenJob(BaseJob) — continuous listeners
    ├── _imap.py                    # Shared IMAP utilities (fetch, decode, extract)
    ├── gmail/
    │   └── handler.py              # Gmail IMAP monitoring
    └── outlook/
        └── handler.py              # Outlook IMAP monitoring
```

## Message Flow

```
1. User @mentions bot in Discord
2. channel/discord reacts with 🙋‍♀️ (acknowledge)
3. channel/discord fetches recent channel history
4. channel/discord calls on_mention callback (injected by core)
5. core builds messages via provider.build_messages(system_prompt, user_prompt)
6. core calls provider.chat(messages) → ChatResponse
7. if tool_calls: core executes tools → provider.append_tool_result() → repeat from 6
8. core returns final reply to channel
9. channel/discord sends reply in Discord
```

## Job Pipeline

```
1. Job fetches new items (IMAP, webhook, etc.)
2. job.format_for_ai(item) → text for AI
3. job.summarize(prompt, text) → AI summary  (attribute set by core, wraps provider.chat)
4. job.format_notification(item, summary) → Discord message
5. notify(notify_channel, message) → send to Discord  (callback from channel)
```

Jobs run as background tasks alongside the reactive @mention flow. Core scans `job/` subdirectories at startup,
sets `summarize` on each job, and starts all jobs. Each job self-manages its enabled/disabled state by reading
`config/jobs.json` on every tick (hot reload — no restart needed).

## Base Classes

### Provider Hierarchy

```
BaseProvider (ABC)
├── OpenAIProvider        → for OpenAI-compatible APIs (Copilot, Ollama, etc.)
└── AnthropicProvider     → for Anthropic API
```

Core reads `provider.api_format` to know how to format tools. Provider handles message formatting (build, append, parse)
but core controls the flow.

### Tool Hierarchy

```
BaseTool (ABC)
├── OpenAITool            → to_openai() mixin
└── AnthropicTool         → to_anthropic() mixin
```

A tool inherits from one or more format mixins. Core calls `tool.to_{api_format}()` to get the right format, then sets
the list on `provider.tools`.

### Job Hierarchy

```
BaseJob (ABC)
├── CronJob              → interval-based scheduling (fetch → process → sleep)
└── ListenJob            → continuous event stream (async for item in listen())
```

A concrete job inherits from `CronJob` or `ListenJob` and implements `fetch()` or `listen()`. The pipeline
(AI summarize → notify) is handled by the base class.

## Configuration

Secrets via `.env` at project root. Operational job config in `config/jobs.json` (hot-reloadable).

| Variable               | Required               | Default                  | Description                                     |
|------------------------|------------------------|--------------------------|-------------------------------------------------|
| `CHANNEL_TYPE`         | No                     | `discord`                | Which channel to use                            |
| `DISCORD_TOKEN`        | When discord           | —                        | Discord bot token                               |
| `AI_PROVIDER`          | No                     | `mock`                   | Which AI provider (`mock`, `copilot`, `ollama`) |
| `GITHUB_TOKEN`         | No                     | —                        | GitHub token (auto-obtained if empty)           |
| `GITHUB_CLIENT_ID`     | No                     | —                        | OAuth App client ID for device flow auth        |
| `AI_MODEL`             | No                     | `gpt-4o-mini`            | Model name                                      |
| `OLLAMA_BASE_URL`      | No                     | `http://localhost:11434` | Ollama API endpoint                             |
| `BRAVE_API_KEY`        | When brave_search tool | —                        | Brave Search API key                            |
| `GMAIL_ADDRESS`        | When gmail job         | —                        | Gmail address for IMAP login                    |
| `GMAIL_APP_PASSWORD`   | When gmail job         | —                        | Gmail App Password                              |
| `OUTLOOK_ADDRESS`      | When outlook job       | —                        | Outlook address for IMAP login                  |
| `OUTLOOK_APP_PASSWORD` | When outlook job       | —                        | Outlook App Password                            |
| `LOG_LEVEL`            | No                     | `DEBUG`                  | Logging level                                   |

### Job Config (`config/jobs.json`)

Schedule, notify channel, prompt, and enabled/disabled state for each job. Edited at runtime — changes take
effect on the next tick without restarting the bot. See the `manage-jobs` skill for schema details.

## Authentication (Copilot Provider)

When `AI_PROVIDER=copilot`, the bot resolves a GitHub token via two methods:

1. **`.env`** — Use `GITHUB_TOKEN` directly if already set
2. **OAuth Device Flow** — Prints a verification code, opens browser, user authorizes on GitHub, token auto-saved to `.env`

Device flow requires `GITHUB_CLIENT_ID`. Register an OAuth App at https://github.com/settings/developers (no client secret needed) and set the client ID in `.env`.

Once obtained, the token is cached in memory and persisted to `.env` — subsequent runs skip the auth flow.

## Logging

- **Console**: INFO level, brief format (`HH:MM:SS`)
- **File**: DEBUG level, detailed format with source location → `config/logs/bot.log`
- Auto-rotates at 5 MB, keeps 3 backups
- Logger hierarchy: `synapulse.*` for app code, `discord` library suppressed to WARNING

Each module uses: `logger = logging.getLogger("synapulse.<module>")`
