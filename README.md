<p align="center">
  <img src="images/logo/Synapulse.svg" alt="Synapulse Logo" width="200">
</p>

# Synapulse

Synapse + Pulse — A personal assistant powered by Discord and AI.

Synapulse is a self-hosted AI assistant that lives in your Discord server. Talk to it by @mentioning, and it will search
the web, manage your to-do list, take notes, set reminders, summarize your emails, execute shell commands, and more. It
remembers your conversations across sessions and can be extended with new tools or connected to hundreds of external
services via MCP.

## Demo

|                             Weather query                             |                     Web search + recommendation                      |
|:---------------------------------------------------------------------:|:--------------------------------------------------------------------:|
| ![Weather](images/display/1.%20what%20is%20the%20weather%20today.gif) | ![Keyboard](images/display/2.%20recommend%20me%20one%20keyboard.gif) |

|                                Reminder (notify mode)                                 |                           Reminder (prompt mode)                            |
|:-------------------------------------------------------------------------------------:|:---------------------------------------------------------------------------:|
| ![Notify](images/display/3.%20notify%20me%20drink%20water%20after%201%20minutes..gif) | ![Prompt](images/display/4.%20notify%20me%20news%20after%201%20minutes.gif) |

## Features

- **AI Chat** — @mention the bot in Discord to chat. Supports multiple AI providers out of the box.
- **Tool Calling** — AI can use tools in a multi-round loop (up to 10 rounds per message). Tools are auto-discovered at
  startup — drop in a new folder and restart.
- **Shell Execution** — The AI proactively uses shell commands for system queries, calculations, git operations, and
  more. Cross-platform: PowerShell on Windows, bash on Linux/macOS.
- **Persistent Memory** — Conversations are saved and summarized automatically. The bot remembers what you talked about
  yesterday, last week, or last month.
- **Task Management** — Track to-dos with priorities and due dates. The AI sees your pending tasks and can remind you
  proactively.
- **Memo / Notes** — Save and search personal notes. Ask "what did I save about X?" and the AI will find it.
- **Reminders** — Set reminders with relative time (`+5m`, `+1h`) or absolute time. Two modes: **notify** for passive
  nudges, **prompt** for scheduled AI actions (e.g. "tell me the weather in 1 hour" — the bot actually checks the
  weather when the time comes).
- **File Operations** — Read, write, search, and manage local files within allowed paths.
- **Email Monitoring** — Background jobs watch Gmail, Outlook, and QQ Mail via IMAP, summarize new emails with AI, and
  push notifications to Discord.
- **MCP Integration** — Connect to any [MCP](https://modelcontextprotocol.io/) server (GitHub, Notion, filesystem,
  databases, etc.) to instantly add hundreds of tools without writing code. On-demand tool loading keeps token usage
  low.
- **Multi-Model Rotation** — YAML-based multi-endpoint config with tag filtering, round-robin rotation, and automatic
  rate-limit fallback.
- **Notification Interaction** — Reply to any bot message (email notification, previous answer) and the AI sees the
  original content as context.
- **Hot-Reload Config** — Models, MCP servers, and job schedules can be updated at runtime — no restart needed.

## Quick Start

Requires **Python 3.11+**.

```bash
# 1. Clone and install
git clone https://github.com/YourUser/Synapulse.git
cd Synapulse
pip install -r apps/bot/requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — fill in DISCORD_TOKEN at minimum

# 3. Run
python -m apps.bot.main
```

The bot runs with the `mock` AI provider by default — no AI keys needed to verify the setup works. Set `AI_PROVIDER` in
`.env` to switch to a real provider.

## Configuration

### Environment Variables (`.env`)

All secrets and provider selection go in `.env`. Copy `.env.example` to get started.

| Variable                                   | Required        | Description                                                                        |
|:-------------------------------------------|:----------------|:-----------------------------------------------------------------------------------|
| `DISCORD_TOKEN`                            | Yes             | Discord bot token ([create one here](https://discord.com/developers/applications)) |
| `AI_PROVIDER`                              | No              | `mock` (default), `copilot`, or `ollama`                                           |
| `AI_MODEL`                                 | No              | Model name, e.g. `gpt-4o-mini` (default)                                           |
| `GITHUB_TOKEN`                             | For copilot     | Auto-obtained via OAuth Device Flow if not set                                     |
| `GITHUB_CLIENT_ID`                         | For copilot     | OAuth App client ID for Device Flow auth                                           |
| `OLLAMA_BASE_URL`                          | For ollama      | Default: `http://localhost:11434`                                                  |
| `BRAVE_API_KEY`                            | For search      | [Get one here](https://brave.com/search/api/)                                      |
| `LOCAL_FILES_ALLOWED_PATHS`                | For files       | Comma-separated paths, e.g. `D:\docs,E:\projects`                                  |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD`     | For Gmail job   | [Create app password](https://myaccount.google.com/apppasswords)                   |
| `OUTLOOK_ADDRESS` / `OUTLOOK_APP_PASSWORD` | For Outlook job | Outlook app password                                                               |
| `QQ_MAIL_ADDRESS` / `QQ_MAIL_APP_PASSWORD` | For QQ Mail job | QQ Mail authorization code                                                         |
| `LOG_LEVEL`                                | No              | `DEBUG` (default), `INFO`, `WARNING`                                               |

### AI Providers

| Provider  | Setup                                                                       | Notes                                      |
|:----------|:----------------------------------------------------------------------------|:-------------------------------------------|
| `mock`    | Nothing needed                                                              | Returns "mock hello" — for testing setup   |
| `copilot` | Set `GITHUB_CLIENT_ID` in `.env`, run bot, follow OAuth prompt in terminal  | Uses GitHub Models API (GPT-4o-mini, etc.) |
| `ollama`  | [Install Ollama](https://ollama.ai), pull a model, set `AI_PROVIDER=ollama` | Fully local, no API keys                   |

### Job Config (`apps/bot/config/jobs.json`)

Copy `jobs.json.example` to `jobs.json` and edit:

```json
{
  "gmail_monitor": {
    "enabled": true,
    "schedule": "*/5 * * * *",
    "notify_channel": "123456789012345678",
    "prompt": "Summarize this email in 2-4 sentences. Capture the key point and any action items."
  },
  "outlook_monitor": {
    "enabled": false,
    "schedule": "*/10 * * * *",
    "notify_channel": "123456789012345678",
    "prompt": "Summarize this email concisely."
  },
  "qqmail_monitor": {
    "enabled": false,
    "schedule": "*/5 * * * *",
    "notify_channel": "123456789012345678",
    "prompt": "Summarize this email concisely."
  }
}
```

- `schedule` — Cron expression (minute hour day month weekday). `*/5 * * * *` = every 5 minutes.
- `notify_channel` — The Discord channel ID where notifications are posted. Right-click a channel in Discord → Copy
  Channel ID.
- `prompt` — The AI prompt used to summarize emails. Customize per job.
- Changes take effect immediately — no restart needed.

## Usage

### Chatting with the Bot

@mention the bot in any Discord channel:

> **@Synapulse** what's the weather in Tokyo?

The bot will search the web and answer. It can chain multiple tool calls in one response — for example, searching, then
saving a memo about what it found.

### Replying to Bot Messages

Reply to any bot message (email notification, previous answer, etc.) and the AI sees the original content:

> **Bot:** New email from John: Meeting moved to 3pm tomorrow...
>
> **You (reply):** translate this to Chinese

The bot sees both your instruction and the original email content.

### Managing Tasks

> **@Synapulse** add a task: submit the report by Friday, high priority

> **@Synapulse** what are my tasks?

> **@Synapulse** mark task 3 as done

Tasks persist across restarts. The AI sees your pending tasks in every conversation and can proactively mention upcoming
deadlines.

### Using Memos

> **@Synapulse** save a memo: the Wi-Fi password is sunshine42

> **@Synapulse** what's the Wi-Fi password?

### Setting Reminders

> **@Synapulse** remind me to drink water in 5 minutes

> **@Synapulse** tell me the weather in 1 hour

> **@Synapulse** remind me every Monday at 9am to check reports

The bot supports two reminder modes:

- **Notify** — passive nudges like "drink water" (static text)
- **Prompt** — scheduled AI actions like "tell me the weather" (the bot actually runs the request when the time comes)

The AI picks the right mode automatically. Relative time (`+5m`, `+1h`, `+2h30m`) and absolute time (ISO 8601) are both
supported.

## Extending Synapulse

### Adding a New Tool

Tools are auto-discovered. To add one:

1. Create `apps/bot/tool/your_tool/handler.py`
2. Define a `Tool` class inheriting from `OpenAITool` and `AnthropicTool`:

```python
from apps.bot.tool.base import AnthropicTool, OpenAITool


class Tool(OpenAITool, AnthropicTool):
    name = "your_tool"
    description = "What this tool does (the AI reads this to decide when to use it)"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look up",
            },
        },
        "required": ["query"],
    }
    usage_hint = "Short hint for the system prompt"

    def validate(self) -> None:
        pass  # Check config/API keys here if needed

    async def execute(self, query: str) -> str:
        # Do the work, return a text result
        return f"Result for {query}"
```

3. Restart the bot. The tool appears in the AI's tool list automatically.

**Available injections** (set by core at startup):

- `self.db` — Database instance for persistence (memos, tasks, etc.)
- `self.send_file` — Callback to send files to Discord (set per-message)
- `self.channel_id` — Current channel ID (set per-message)

### Adding an MCP Server

MCP (Model Context Protocol) lets you connect external tool servers without writing any code.

**Option A: Static config file**

Edit `apps/bot/config/mcp.json`:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/home/user/docs"
      ],
      "env": {},
      "timeout": 30000
    },
    "github": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-github"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxxx"
      }
    }
  }
}
```

Restart the bot. It connects to all configured servers and discovers their tools automatically.

**Option B: Via Discord chat**

Just tell the bot:

> **@Synapulse** connect an MCP server called "github" with command "npx" and
> args ["-y", "@modelcontextprotocol/server-github"]

The AI calls the `mcp_server` tool to connect, and the new tools are available immediately — no restart needed. The
config is persisted and survives restarts.

> **@Synapulse** what MCP servers do I have?

> **@Synapulse** what tools does the github server provide?

> **@Synapulse** disconnect the filesystem server

Browse available MCP servers at [MCP Server Directory](https://github.com/modelcontextprotocol/servers).

### Adding a New AI Provider

1. Create `apps/bot/provider/your_provider/chat.py`
2. Define a `Provider` class inheriting from `OpenAIProvider` or `AnthropicProvider`
3. Implement `authenticate()` and `chat()`
4. Set `AI_PROVIDER=your_provider` in `.env`

### Adding a New Background Job

1. Create `apps/bot/job/your_job/handler.py`
2. Define a `Job` class inheriting from `CronJob` or `ListenJob`
3. Add the job's config entry to `jobs.json`
4. Restart the bot

## Built-in Tools

| Tool           | Description                                                  | Requires                    |
|:---------------|:-------------------------------------------------------------|:----------------------------|
| `shell_exec`   | Execute shell commands (cross-platform: PowerShell / bash)   | `LOCAL_FILES_ALLOWED_PATHS` |
| `local_files`  | Read, write, search, and manage local files                  | `LOCAL_FILES_ALLOWED_PATHS` |
| `brave_search` | Search the web via Brave Search API                          | `BRAVE_API_KEY`             |
| `weather`      | Current weather and 3-day forecast via OpenWeatherMap        | `OPENWEATHER_API_KEY`       |
| `memo`         | Save, search, list, delete personal notes                    | —                           |
| `reminder`     | Timed reminders with notify/prompt modes and relative time   | —                           |
| `task`         | To-do list with priority and due dates                       | —                           |
| `mcp_server`   | Manage MCP server connections (add, remove, list, use tools) | —                           |

## Project Structure

```
Synapulse/
├── apps/bot/                    # Main application
│   ├── main.py                  # Entry point
│   ├── config/                  # Settings, prompts, logging
│   ├── core/                    # Orchestration (bootstrap, tool-call loop, loader, reminder checker)
│   ├── provider/                # AI providers (mock, copilot, ollama)
│   ├── channel/                 # Platform I/O (discord)
│   ├── tool/                    # AI tools (auto-discovered)
│   ├── job/                     # Background jobs (auto-discovered)
│   ├── mcp/                     # MCP client manager
│   └── memory/                  # Persistent storage (JSON-based)
├── config/                      # Runtime config (models.yaml, mcp.json, jobs.json)
├── output/                      # Runtime output (logs, data)
├── tests/                       # Unit tests (pytest)
├── scripts/                     # Build, test, run scripts
├── requirements/                # Requirement & design documents
└── docs/                        # Design notes
```

## Architecture

```
User ──→ Discord ──→ Channel Layer ──→ Core (tool-call loop) ──→ AI Provider
                                          │
                                          ├── Native Tools (search, memo, task, ...)
                                          ├── MCP Tools (GitHub, Notion, filesystem, ...)
                                          ├── Memory (conversations, summaries)
                                          └── Background Jobs (email monitors)
```

Key design principles:

- **Dynamic loading** — Tools and jobs are auto-discovered via folder scanning. Drop in a new folder, restart, done.
- **Inversion of control** — Core injects callbacks into passive layers. No layer imports another peer layer.
- **Graceful degradation** — Missing config, failed tools, crashed MCP servers — everything is isolated. The bot keeps
  running.

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Build check (syntax verification)
bash scripts/build.sh

# Run the bot
python -m apps.bot.main
```

## License

[MIT](LICENSE)
