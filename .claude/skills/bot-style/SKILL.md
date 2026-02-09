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
               ├─ config.validate()
               ├─ config.log_summary()
               ├─ importlib: load channel by CHANNEL_TYPE
               ├─ importlib: load provider by AI_PROVIDER (lazy, on first call)
               └─ channel.run(on_mention=handle_mention)   ← inject callback
                       ↓
              channel receives message
                       ↓
              channel calls on_mention(content, history)    ← callback into core
                       ↓
              core builds prompt, calls provider, returns reply
                       ↓
              channel sends reply
```

### Core is the brain

- **main.py** — Bootstrap only: init logging, then call `core.start()`. No orchestration logic here.
- **core/** — THE orchestrator. Owns the entire flow: validates config, dynamically loads channel and provider, provides callbacks to channel, processes messages, calls provider. All decision-making lives here.
- **channel/** — Platform I/O only. Receive messages, send replies, add reactions. NEVER import from `core/` or `provider/`. Channel receives a callback from core and calls it — it does not know who is on the other end.
- **provider/** — Pure AI provider calls. Each provider is a subfolder (`provider/mock/`, `provider/copilot/`, ...) with a `chat.py` exposing `async def chat(message: str) -> str`. No knowledge of channels or core.
- **config/** — Settings and logging, shared by all layers.

### Dynamic Loading — No match-case

Channel and provider are loaded purely by `.env` values via `importlib`:

```python
# AI_PROVIDER=mock → apps.bot.provider.mock.chat
importlib.import_module(f"apps.bot.provider.{config.AI_PROVIDER}.chat")

# CHANNEL_TYPE=discord → apps.bot.channel.discord.client
importlib.import_module(f"apps.bot.channel.{config.CHANNEL_TYPE}.client")
```

No match-case, no if-else. Add a new provider/channel by creating the folder — core doesn't change.

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

- New channel (Telegram, Slack, ...): add `channel/<name>/client.py` with `def run(on_mention)`. Set `CHANNEL_TYPE=<name>` in `.env`.
- New AI provider: add `provider/<name>/chat.py` with `async def chat(message: str) -> str`. Set `AI_PROVIDER=<name>` in `.env`.
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
- Required vars are validated in `config.validate()`, called once at startup
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
- Keep modules focused: one responsibility per file
- Catch specific exceptions; use bare `except Exception` only as a last resort with `logger.exception()`
