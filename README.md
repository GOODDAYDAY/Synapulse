# Synapulse

Synapse + Pulse — A personal assistant powered by Discord and AI.

## What is this

A modular personal assistant that lives in Discord. It can chat with AI, and more features are on the way (email summarization, scheduled tasks, etc.).

## Quick Start

```bash
cd apps/bot
pip install -r requirements.txt
cp ../../.env.example ../../.env   # fill in your tokens
python -m apps.bot.main             # run from project root
```

## Project Structure

```
Synapulse/
├── .env.example            # Environment variable template
└── apps/
    ├── bot/                # Discord bot (see apps/bot/README.md)
    └── web/                # Web dashboard (planned)
```

## License

[MIT](LICENSE)
