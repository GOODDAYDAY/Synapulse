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
               ├─ core/loader.scan_tools(): auto-scan tool/ subfolders
               │       └─ tool.validate()
               ├─ core/loader.format_tools_for_provider(tools, provider.api_format)
               │       └─ tool.to_{api_format}() → list[dict]
               ├─ provider.tools = formatted list
               ├─ core/loader.scan_jobs(): auto-scan job/ subfolders
               │       └─ inject summarize callback into each job
               ├─ importlib: load channel by CHANNEL_TYPE
               │       ├─ Channel()
               │       └─ channel.validate()
               ├─ channel.run(on_mention=mention.make_mention_handler(provider, tools))
               └─ job.start(channel.send) for each job  (background tasks)
```

### Mention (tool-call loop)

```
channel receives message → calls on_mention(content, history)
       ↓
core/mention.handle_mention:
  build user prompt from content + history
       ↓
  provider.build_messages(SYSTEM_PROMPT, user_prompt)
       ↓
  loop (max 10 rounds):
    provider.chat(messages) → ChatResponse
    if text (no tool_calls): return text
    for each tool_call:
      tool.execute(**args) → result
      provider.append_tool_result(messages, call, result)
       ↓
  channel sends final reply
```

### Job Pipeline

```
job.start(notify=channel.send)  (background task)
       ↓
  loop:
    hot-reload config via load_job_config()
    guard: disabled / validation fail / no notify_channel → sleep 60s
    CronJob: wait for next cron time → fetch() → list[dict]
    ListenJob: async for item in listen()
       ↓
    job.process(item, prompt):
      format_for_ai(item) → text
      summarize(prompt, text) → AI summary  (injected by core)
      format_notification(item, summary) → message
       ↓
    notify(channel_id, message) → send to Discord
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
     wait_until_ready()                                    abstract
     send(channel_id, message)                             abstract

job/base.py
├─ BaseJob (ABC)
│    name: str                                             class attribute
│    prompt: str                                           class default (overridable via jobs.json)
│    summarize: SummarizeCallback                          set by core at startup
│    validate()                                            optional override
│    format_for_ai(item) -> str                            default: key-value pairs
│    format_notification(item, summary) -> str             default: return summary
│    process(item, prompt) -> str                          template method
│    start(notify: NotifyCallback)                         abstract
├─ CronJob(BaseJob)
│    schedule: str                                         cron expression (overridable via jobs.json)
│    fetch() -> list[dict]                                 abstract
└─ ListenJob(BaseJob)
     listen() -> AsyncIterator[dict]                       abstract

Data classes (provider/base.py):
  ToolCall(id, name, arguments)
  ChatResponse(text, tool_calls)
```

## Dependency Direction

```
main → core → channel (via callback injection)
         ├──→ provider (tools set by core, messages passed by core)
         ├──→ tool (executed by core, formatted by core)
         └──→ job (summarize + notify callbacks injected by core)
```

- channel, provider, tool, job import NOTHING from each other or from core.
- config/ is the only shared import across all layers.

## Extending

- **New channel**: `channel/<name>/client.py` → `class Channel(BaseChannel)`. Set `CHANNEL_TYPE=<name>`.
- **New provider**: `provider/<name>/chat.py` → `class Provider(OpenAIProvider)` or `class Provider(AnthropicProvider)`.
  Set `AI_PROVIDER=<name>`.
- **New tool**: `tool/<name>/handler.py` → `class Tool(OpenAITool, AnthropicTool)`. Auto-scanned — no config change.
- **New job**: `job/<name>/handler.py` → `class Job(CronJob)` or `class Job(ListenJob)`. Auto-scanned — configure via
  `jobs.json`.

## Code Style

- Python 3.11 type hints (`str | None`, `TypeAlias`)
- `async/await` for all I/O
- No empty `__init__.py`
- Imports: stdlib → third-party → local, separated by blank lines
- Absolute imports: `from apps.bot.config.settings import config`
- Add docstrings to modules, classes, and public functions
- Catch specific exceptions; bare `except Exception` only with `logger.exception()`
- Logger per module: `logger = logging.getLogger("synapulse.<module>")`
- Lazy formatting: `logger.info("Got %s", value)` not f-strings
- Never log secrets; use `_mask()` from config
