# Bot

The core bot application of Synapulse.

## Architecture

```
channel/*  ──→  core/handler  ──→  provider/*
  (I/O)        (orchestrate)      (AI adapter)
                    ↕
                  tool/*
               (capabilities)
```

High cohesion, low coupling. Each layer has one job:

- **core/** — THE orchestrator. Loads channel, provider, and tools. Injects callbacks, orchestrates the tool-call loop.
  All coordination lives here.
- **channel/** — Platform I/O only. Receives a callback and calls it. Knows nothing about providers or tools.
- **provider/** — AI API adapter. Formats messages for a specific LLM API. Knows nothing about channels or tools.
- **tool/** — Capabilities (search, etc.). Each tool defines itself and formats its definition for different APIs. Knows
  nothing about other layers.
- **config/** — Settings, logging, and prompts. Shared by all layers.

## Directory Structure

```
bot/
├── main.py                         # Bootstrap: logging → core.start()
├── requirements.txt
├── config/
│   ├── settings.py                 # Frozen dataclass, secret masking
│   ├── logging.py                  # dictConfig with console + rotating file
│   ├── prompts.py                  # Static system prompt
│   └── logs/                       # Log files (git-ignored)
├── core/
│   └── handler.py                  # Orchestration: load all layers, tool-call loop
├── provider/
│   ├── base.py                     # BaseProvider, OpenAIProvider, AnthropicProvider
│   ├── mock/
│   │   └── chat.py                 # Returns "mock hello" (for testing)
│   └── copilot/
│       ├── chat.py                 # GitHub Models API (OpenAI-compatible)
│       └── auth.py                 # .env / OAuth Device Flow, auto-save to .env
├── channel/
│   ├── base.py                     # BaseChannel ABC (validate + run)
│   └── discord/
│       └── client.py               # Discord event listener & reply
└── tool/
    ├── base.py                     # BaseTool, OpenAITool, AnthropicTool
    └── brave_search/
        └── handler.py              # Brave Search API
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

## Base Classes

### Provider Hierarchy

```
BaseProvider (ABC)
├── OpenAIProvider        → for OpenAI-compatible APIs (GitHub Models, Azure, etc.)
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

## Configuration

All config via `.env` at project root.

| Variable           | Required               | Default       | Description                              |
|--------------------|------------------------|---------------|------------------------------------------|
| `CHANNEL_TYPE`     | No                     | `discord`     | Which channel to use                     |
| `DISCORD_TOKEN`    | When discord           | —             | Discord bot token                        |
| `AI_PROVIDER`      | No                     | `mock`        | Which AI provider (`mock`, `copilot`)    |
| `GITHUB_TOKEN`     | No                     | —             | GitHub token (auto-obtained if empty)    |
| `GITHUB_CLIENT_ID` | No                     | —             | OAuth App client ID for device flow auth |
| `AI_MODEL`         | No                     | `gpt-4o-mini` | Model name                               |
| `BRAVE_API_KEY`    | When brave_search tool | —             | Brave Search API key                     |
| `LOG_LEVEL`        | No                     | `DEBUG`       | Logging level                            |

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
