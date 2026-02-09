<p align="center">
  <img src="images/logo/Synapulse.svg" alt="Synapulse Logo" width="200">
</p>

# Synapulse

Synapse + Pulse — A personal assistant powered by Discord and AI.

## Features

- **AI Chat** — @mention the bot in Discord to chat. Supports multiple providers: local Ollama, GitHub Copilot, or bring
  your own.
- **Tool Calling** — AI can use tools (web search, etc.) in a multi-round loop. Tools are auto-discovered at startup.
- **Email Monitoring** — Background jobs watch Gmail / Outlook via IMAP, summarize new emails with AI, and notify a
  Discord channel.
- **Hot-Reload Config** — Job schedules, prompts, and enabled/disabled state live in a JSON file. Edit at runtime, no
  restart needed.

## Quick Start

```bash
pip install -r apps/bot/requirements.txt
cp .env.example .env                       # fill in your tokens
python -m apps.bot.main                    # run from project root
```

## Project Structure

```
Synapulse/
├── .env.example                # Environment variable template
├── images/logo/                # Project logo (SVG + JPEG)
└── apps/
    ├── bot/                    # Discord bot (see apps/bot/README.md)
    └── web/                    # Web dashboard (planned)
```

See [`apps/bot/README.md`](apps/bot/README.md) for architecture, configuration, and extension guides.

## License

[MIT](LICENSE)
