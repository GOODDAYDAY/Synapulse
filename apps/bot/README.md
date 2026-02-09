# Bot

The core bot application of Synapulse.

## Architecture

```
channel/*  ──→  core/handler  ──→  provider/*
  (I/O)        (orchestrate)      (AI provider)
```

High cohesion, low coupling. Each layer has one job:

- **channel/** — Transport layer. Handles platform-specific I/O only (receive messages, send replies, add reactions). Knows nothing about providers or business logic.
- **core/** — Orchestration layer. Dynamically loads channel and provider via `importlib`, injects callbacks into channel, builds context, calls provider.
- **provider/** — AI provider layer. Each provider is a subfolder with a `chat.py`. Takes a prompt, returns a response. Knows nothing about channels.
- **config/** — Settings and logging. Loaded once at startup, shared across all layers.
- **skill/** — (planned) Pluggable skills the bot can perform.
- **agent/** — (planned) Multi-step agent workflows.

## Directory Structure

```
bot/
├── main.py                         # Bootstrap: logging → core.start()
├── requirements.txt
├── config/
│   ├── settings.py                 # Frozen dataclass, secret masking
│   ├── logging.py                  # dictConfig with console + rotating file
│   └── logs/                       # Log files (git-ignored)
├── core/
│   └── handler.py                  # Orchestration: load channel/provider, handle messages
├── provider/
│   ├── base.py                     # BaseProvider ABC (authenticate + chat)
│   ├── mock/
│   │   └── chat.py                 # Returns "mock hello" (for testing)
│   └── copilot/
│       ├── chat.py                 # GitHub Models API
│       └── auth.py                 # .env / OAuth Device Flow, auto-save to .env
├── channel/
│   ├── base.py                     # BaseChannel ABC (validate + run)
│   └── discord/
│       └── client.py               # Discord event listener & reply
├── agent/
└── skill/
```

## Message Flow

```
1. User @mentions bot in Discord
2. channel/discord reacts with ☝️ (acknowledge)
3. channel/discord fetches recent channel history
4. channel/discord calls on_mention callback (injected by core)
5. core/handler builds context prompt, calls provider
6. provider returns reply
7. core/handler returns reply to channel
8. channel/discord sends reply in Discord
```

## Configuration

All config via `.env` at project root.

| Variable | Required | Default | Description |
|---|---|---|---|
| `CHANNEL_TYPE` | No | `discord` | Which channel to use |
| `DISCORD_TOKEN` | When discord | — | Discord bot token |
| `AI_PROVIDER` | No | `mock` | Which AI provider (`mock`, `copilot`) |
| `GITHUB_TOKEN` | No | — | GitHub token (auto-obtained if empty) |
| `GITHUB_CLIENT_ID` | No | — | OAuth App client ID for device flow auth |
| `AI_MODEL` | No | `gpt-4o-mini` | Model name |
| `LOG_LEVEL` | No | `DEBUG` | Logging level |

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
