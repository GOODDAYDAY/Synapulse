import logging
from collections.abc import Callable, Coroutine
from typing import Any

import discord

from apps.bot.config.settings import config

logger = logging.getLogger("synapulse.discord")

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)

HISTORY_LIMIT = 5

# Callback set by core, channel doesn't know who handles the message
_on_mention: Callable[[str, list[dict[str, str]]], Coroutine[Any, Any, str]] | None = None


@bot.event
async def on_ready():
    logger.info("Bot is online as %s (id=%s)", bot.user, bot.user.id)
    for guild in bot.guilds:
        channels = [ch.name for ch in guild.text_channels]
        logger.info("  Guild: %s | text channels: %s", guild.name, ", ".join(channels))


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    logger.debug("[#%s] %s: %s", message.channel, message.author, message.content)

    if not (bot.user and bot.user in message.mentions):
        return

    content = message.content.replace(f"<@{bot.user.id}>", "").strip()
    if not content:
        content = "Hello!"

    await message.add_reaction("\U0000261d")

    history = []
    async for msg in message.channel.history(limit=HISTORY_LIMIT, before=message):
        if msg.author == bot.user or not msg.content:
            continue
        history.append({"author": msg.author.display_name, "content": msg.content})
    history.reverse()

    async with message.channel.typing():
        reply = await _on_mention(content, history)

    await message.reply(reply)


def run(on_mention: Callable[[str, list[dict[str, str]]], Coroutine[Any, Any, str]]) -> None:
    global _on_mention
    _on_mention = on_mention
    logger.info("Starting Discord client...")
    bot.run(config.DISCORD_TOKEN, log_handler=None)
