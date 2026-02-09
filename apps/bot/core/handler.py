import importlib
import logging
from collections.abc import Callable, Coroutine
from typing import Any, TypeAlias

from apps.bot.config.settings import config

logger = logging.getLogger("synapulse.core")

ChatFn: TypeAlias = Callable[[str], Coroutine[Any, Any, str]]

_chat: ChatFn | None = None


async def handle_mention(
    content: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    global _chat
    if _chat is None:
        module = importlib.import_module(f"apps.bot.provider.{config.AI_PROVIDER}.chat")
        _chat = module.chat
        logger.info("AI provider loaded: %s", config.AI_PROVIDER)

    logger.info("Handling mention (length=%d, history=%d)", len(content), len(history or []))

    if history:
        context = "\n".join(f"{m['author']}: {m['content']}" for m in history)
        prompt = f"[Recent channel messages]\n{context}\n\n[User message]\n{content}"
    else:
        prompt = content

    reply = await _chat(prompt)
    logger.debug("Reply generated (length=%d)", len(reply))
    return reply


def start() -> None:
    config.validate()
    config.log_summary()

    channel = importlib.import_module(f"apps.bot.channel.{config.CHANNEL_TYPE}.client")
    logger.info("Starting with channel=%s, ai=%s", config.CHANNEL_TYPE, config.AI_PROVIDER)
    channel.run(on_mention=handle_mention)
