"""
Core orchestrator — the brain of the bot.

Responsibilities:
- Load and initialize provider and channel based on .env config
- Each implementation validates its own config (no central if-else)
- Inject handle_mention callback into channel
- Build prompt context and delegate to provider
"""

import importlib
import logging

from apps.bot.config.settings import config
from apps.bot.provider.base import BaseProvider

logger = logging.getLogger("synapulse.core")

_provider: BaseProvider | None = None


async def handle_mention(
    content: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Process an @mention: build context from history, call provider, return reply."""
    logger.info("Handling mention (length=%d, history=%d)", len(content), len(history or []))

    if history:
        context = "\n".join(f"{m['author']}: {m['content']}" for m in history)
        prompt = f"[Recent channel messages]\n{context}\n\n[User message]\n{content}"
    else:
        prompt = content

    reply = await _provider.chat(prompt)
    logger.debug("Reply generated (length=%d)", len(reply))
    return reply


def start() -> None:
    """Bootstrap the bot: config → provider → channel."""
    global _provider

    config.log_summary()

    # Init provider — authenticate() handles its own validation
    provider_module = importlib.import_module(f"apps.bot.provider.{config.AI_PROVIDER}.chat")
    _provider = provider_module.Provider()
    _provider.authenticate()
    logger.info("AI provider ready: %s", config.AI_PROVIDER)

    # Init channel — validate() handles its own config checks
    channel_module = importlib.import_module(f"apps.bot.channel.{config.CHANNEL_TYPE}.client")
    channel = channel_module.Channel()
    channel.validate()
    logger.info("Starting with channel=%s, ai=%s", config.CHANNEL_TYPE, config.AI_PROVIDER)
    channel.run(on_mention=handle_mention)
