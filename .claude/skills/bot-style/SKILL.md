---
name: bot-style
description: Implementation details and code conventions for the Synapulse bot. Contracts, call chains, and style rules for apps/bot/.
disable-model-invocation: false
user-invocable: false
---

# Implementation Details

Concrete contracts, patterns, and style rules for `apps/bot/`.

## Call Chain

```
main.py → core/handler.start()
               ├─ config.log_summary()
               ├─ importlib: load provider by AI_PROVIDER
               │       ├─ Provider()
               │       └─ provider.authenticate()
               ├─ _scan_tools(): auto-scan tool/ subfolders
               │       └─ tool.validate()
               ├─ _format_tools_for_provider(tools, provider.api_format)
               │       └─ tool.to_{api_format}() → list[dict]
               ├─ provider.tools = formatted list
               ├─ importlib: load channel by CHANNEL_TYPE
               │       ├─ Channel()
               │       └─ channel.validate()
               └─ channel.run(on_mention=handle_mention)
                       ↓
              channel receives message → calls on_mention(content, history)
                       ↓
              core builds prompt → provider.build_messages(system, user)
                       ↓
              provider.chat(messages) → ChatResponse
                       ↓
              if tool_calls: core executes tools → provider.append_tool_result() → loop
                       ↓
              channel sends final reply
```

## Base Class Contracts

```
provider/base.py
├─ BaseProvider (ABC)
│    api_format: str                                       class attribute
│    tools: list[dict]                                     property, set by core
│    authenticate()                                        optional override
│    build_messages(system_prompt, user_prompt) -> list     abstract
│    append_tool_result(messages, tool_call, result)        abstract
│    parse_tool_calls(raw_msg) -> list[ToolCall]           abstract
│    chat(messages) -> ChatResponse                        abstract
├─ OpenAIProvider(BaseProvider)                            api_format = "openai"
│    implements build_messages, append_tool_result, parse_tool_calls
└─ AnthropicProvider(BaseProvider)                         api_format = "anthropic"
     implements build_messages, append_tool_result, parse_tool_calls

tool/base.py
├─ BaseTool (ABC)
│    name, description, parameters (JSON Schema)           class attributes
│    validate()                                            optional override
│    execute(**kwargs) -> str                               abstract
├─ OpenAITool(BaseTool)                                    mixin
│    to_openai() -> dict
└─ AnthropicTool(BaseTool)                                 mixin
     to_anthropic() -> dict

channel/base.py
└─ BaseChannel (ABC)
     validate()                                            optional override
     run(on_mention: MentionHandler)                       abstract

Data classes (provider/base.py):
  ToolCall(id, name, arguments)
  ChatResponse(text, tool_calls)
```

## Dependency Direction

```
main → core → channel (via callback injection)
         ├──→ provider (tools set by core, messages passed by core)
         └──→ tool (executed by core, formatted by core)
```

- channel, provider, tool import NOTHING from each other or from core.
- config/ is the only shared import across all layers.

## Authentication (Copilot)

```
.env (GITHUB_TOKEN) → OAuth Device Flow (GITHUB_CLIENT_ID) → RuntimeError
                              ↓
                        auto-save to .env
```

Form-encoded POST to GitHub. Prints verification code, opens browser, polls for token.

## Extending

- **New channel**: `channel/<name>/client.py` → `class Channel(BaseChannel)`. Set `CHANNEL_TYPE=<name>`.
- **New provider**: `provider/<name>/chat.py` → `class Provider(OpenAIProvider)` or `class Provider(AnthropicProvider)`.
  Set `AI_PROVIDER=<name>`.
- **New tool**: `tool/<name>/handler.py` → `class Tool(OpenAITool, AnthropicTool)`. Auto-scanned — no config change.

## Logging

- Logger per module: `logger = logging.getLogger("synapulse.<module>")`
- Lazy formatting: `logger.info("Got %s", value)` not f-strings
- All log messages in English
- Never log secrets; use `_mask()` from config
- Levels: DEBUG (trace), INFO (lifecycle), WARNING (degraded), ERROR (failures), EXCEPTION (unexpected)

## Configuration

- Frozen `Config` dataclass in `config/settings.py`
- Access: `from apps.bot.config.settings import config`
- Static prompts in `config/prompts.py`
- Config only loads and displays — validation delegated to implementations

## Code Style

- Python 3.11 type hints (`str | None`, `TypeAlias`)
- `async/await` for all I/O
- No empty `__init__.py`
- Imports: stdlib → third-party → local, separated by blank lines
- Absolute imports: `from apps.bot.config.settings import config`
- Add docstrings to modules, classes, and public functions
- Catch specific exceptions; bare `except Exception` only with `logger.exception()`
