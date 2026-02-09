"""Discord channel — handles all Discord-specific I/O."""

import asyncio
import logging

import discord

from apps.bot.channel.base import BaseChannel, MentionHandler
from apps.bot.config.settings import config

logger = logging.getLogger("synapulse.discord")

HISTORY_LIMIT = 5


class Channel(BaseChannel):

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        self._bot = discord.Client(intents=intents)
        self._ready = asyncio.Event()

    def validate(self) -> None:
        """Ensure Discord token is configured."""
        if not config.DISCORD_TOKEN:
            raise EnvironmentError(
                "DISCORD_TOKEN is required when CHANNEL_TYPE=discord. "
                "Get yours at https://discord.com/developers/applications"
            )

    async def run(self, on_mention: MentionHandler) -> None:
        """Start the Discord client and listen for @mentions."""
        bot = self._bot

        @bot.event
        async def on_ready():
            logger.info("Bot is online as %s (id=%s)", bot.user, bot.user.id)
            for guild in bot.guilds:
                channels = [ch.name for ch in guild.text_channels]
                logger.info("  Guild: %s | text channels: %s", guild.name, ", ".join(channels))
            self._ready.set()

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

            # Acknowledge with reaction
            await message.add_reaction("\U0001f64b\u200d\u2640\ufe0f")

            # Gather recent history for context
            history = []
            async for msg in message.channel.history(limit=HISTORY_LIMIT, before=message):
                if msg.author == bot.user or not msg.content:
                    continue
                history.append({"author": msg.author.display_name, "content": msg.content})
            history.reverse()

            # Delegate to core via callback
            async with message.channel.typing():
                reply = await on_mention(content, history)

            await message.channel.send(reply)

        logger.info("Starting Discord client...")
        async with bot:
            await bot.start(config.DISCORD_TOKEN, reconnect=True)

    async def wait_until_ready(self) -> None:
        """Block until the Discord client is connected and ready."""
        await self._ready.wait()

    async def send(self, channel_id: str, message: str) -> None:
        """Send a message to a Discord channel by ID."""
        ch = self._bot.get_channel(int(channel_id))
        if ch:
            await ch.send(message)
