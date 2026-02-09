---
name: bot-style
description: Architecture and code style for the Synapulse bot. Apply these rules when writing or modifying code under apps/bot/.
disable-model-invocation: false
user-invocable: false
---

When writing or modifying code under `apps/bot/`, follow these conventions:

## Architecture — High Cohesion, Low Coupling

### Call Chain

```
main.py → core/handler.start()
               ├─ config.log_summary()
               ├─ importlib: load provider by AI_PROVIDER
               │       ├─ Provider()
               │       └─ provider.authenticate()   ← provider validates its own config
               ├─ importlib: load channel by CHANNEL_TYPE
               │       ├─ Channel()
               │       └─ channel.validate()         ← channel validates its own config
               └─ channel.run(on_mention=handle_mention)
                       ↓
              channel receives message → calls on_mention callback
                       ↓
              core builds prompt → calls provider.chat()
                       ↓
              channel sends reply
```

### Core is the brain

- **main.py** — Bootstrap only: init logging, then call `core.start()`. No orchestration logic here.
- **core/** — THE orchestrator. Dynamically loads channel and provider, calls their lifecycle methods, injects callbacks. All coordination lives here.
- **channel/** — Platform I/O only. NEVER import from `core/` or `provider/`. Receives a callback and calls it.
- **provider/** — Pure AI calls. NEVER import from `core/` or `channel/`.
- **config/** — Settings and logging, shared by all layers.

### Self-Validating Implementations — No Central if-else

Config does NOT know which fields belong to which implementation. Each implementation validates itself:

- `BaseProvider.authenticate()` — provider checks its own credentials (e.g. copilot resolves GITHUB_TOKEN from .env, or runs OAuth Device Flow, auto-saving to .env)
- `BaseChannel.validate()` — channel checks its own config (e.g. discord checks DISCORD_TOKEN)
- `Config` class only loads and displays values. NEVER add implementation-specific if-else to Config.

This means adding a new provider/channel that needs a new env var requires ZERO changes to `config/settings.py` validation logic — the new implementation handles it.

### Authentication Pattern — Graceful Fallback with Auto-Persist

Provider authentication tries sources in order and auto-persists credentials. Example (copilot):

```
.env (GITHUB_TOKEN) → OAuth Device Flow (GITHUB_CLIENT_ID) → RuntimeError
                              ↓
                        save to .env
```

Once a token is obtained, it is saved to `.env` so subsequent runs use it directly.

### Base Classes — Explicit Contracts

```
provider/base.py → BaseProvider
    authenticate()              optional, override for auth at startup
    chat(message) -> str        required, abstract

channel/base.py → BaseChannel
    validate()                  optional, override for config checks
    run(on_mention)             required, abstract
```

Each implementation module exports a class named `Provider` or `Channel` that extends the base. Core instantiates via dynamic import — no factory, no registry, just convention.

### Dynamic Loading — No match-case, No if-else

Channel and provider are loaded purely by `.env` values via `importlib`:

```python
# AI_PROVIDER=mock → apps.bot.provider.mock.chat → Provider class
importlib.import_module(f"apps.bot.provider.{config.AI_PROVIDER}.chat")

# CHANNEL_TYPE=discord → apps.bot.channel.discord.client → Channel class
importlib.import_module(f"apps.bot.channel.{config.CHANNEL_TYPE}.client")
```

No match-case, no if-else in core. Add a new provider/channel by creating the folder — core doesn't change.

### Dependency Direction

```
main → core → channel (via callback injection)
         ↓
       provider
```

- core dynamically imports channel and provider.
- channel imports NOTHING from core or provider. It only calls the callback it was given.
- provider imports NOTHING from core or channel.
- This is inversion of control: core injects behavior into channel, not the other way around.

### Extending

- New channel: add `channel/<name>/client.py` with `class Channel(BaseChannel)`. Set `CHANNEL_TYPE=<name>` in `.env`.
- New AI provider: add `provider/<name>/chat.py` with `class Provider(BaseProvider)`. Set `AI_PROVIDER=<name>` in `.env`.
- New feature (skill, agent, ...): core orchestrates it; channel and provider stay focused on their single responsibility.

## Logging

- Every module gets its own logger: `logger = logging.getLogger("synapulse.<module_name>")`
- Logger names follow the package path: `synapulse.config`, `synapulse.provider.mock`, `synapulse.discord`
- Log levels:
  - `DEBUG` — verbose trace (message content, payload sizes, response snippets)
  - `INFO` — key lifecycle events (bot online, config loaded, connection established)
  - `WARNING` — degraded but functional (missing optional config, fallback activated)
  - `ERROR` — failures that affect the user (API errors, missing required config)
  - `EXCEPTION` — unexpected errors (use `logger.exception()` inside except blocks)
- All log messages in English
- Use lazy formatting: `logger.info("Got %s", value)` not `logger.info(f"Got {value}")`
- Never log secrets; use the `_mask()` helper from `config/settings.py` when logging config values

## Configuration

- All env vars are defined in `config/settings.py` as fields on the frozen `Config` dataclass
- Access via the singleton: `from apps.bot.config.settings import config`
- Config only loads and displays. Validation is delegated to each implementation's lifecycle methods
- Optional vars have sensible defaults
- Selection (channel type, AI provider) is done via `.env` with defaults, so the bot runs out of the box

## Imports

- Standard library → third-party → local app, separated by blank lines
- Local imports use absolute paths: `from apps.bot.config.settings import config`
- Lazy imports (inside functions) only when needed to avoid circular deps

## Code Style

- Python 3.11 type hints (use `TypeAlias` for type aliases, `str | None` for unions)
- `async/await` for all I/O-bound operations
- No `__init__.py` files unless package-level initialization is needed
- `if __name__ == "__main__"` only in the single external entry point (`main.py`). No other module should have it.
- Keep modules focused: one responsibility per file
- Prefer guard clauses (positive `if` → do work → return) over negative checks (`if not` → raise). Happy path reads top-down, error at the bottom.
- Add docstrings to modules, classes, and public functions
- Catch specific exceptions; use bare `except Exception` only as a last resort with `logger.exception()`
