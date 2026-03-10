"""Discord channel — handles all Discord-specific I/O."""

import asyncio
import logging

import discord

from apps.bot.channel.base import BaseChannel, MentionHandler
from apps.bot.config.settings import config

logger = logging.getLogger("synapulse.discord")

HISTORY_LIMIT = 5
# Discord enforces a 2000-character limit per message.
DISCORD_MSG_LIMIT = 2000
# Max characters to extract from a referenced (replied-to) bot message.
_REFERENCE_CONTENT_CAP = 2000


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

            # Extract referenced message content if user replied to a bot message
            referenced_content = None
            if message.reference:
                try:
                    ref_msg = message.reference.resolved
                    if ref_msg is None:
                        ref_msg = await message.channel.fetch_message(message.reference.message_id)
                    if ref_msg and ref_msg.author == bot.user and ref_msg.content:
                        referenced_content = ref_msg.content[:_REFERENCE_CONTENT_CAP]
                        logger.debug("Extracted referenced bot message (%d chars)",
                                     len(referenced_content))
                except Exception:
                    logger.warning("Failed to fetch referenced message, ignoring")

            # Gather recent history for context
            history = []
            async for msg in message.channel.history(limit=HISTORY_LIMIT, before=message):
                if msg.author == bot.user or not msg.content:
                    continue
                history.append({"author": msg.author.display_name, "content": msg.content})
            history.reverse()

            # Delegate to core via callback
            channel_id = str(message.channel.id)
            user_id = str(message.author.id)
            async with message.channel.typing():
                reply = await on_mention(content, channel_id, user_id, history, referenced_content)

            await self._send_chunks(message.channel, reply)

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
            await self._send_chunks(ch, message)

    async def send_file(self, channel_id: str, file_path: str, comment: str = "") -> None:
        """Send a file to a Discord channel by ID."""
        ch = self._bot.get_channel(int(channel_id))
        if ch:
            await ch.send(content=comment or None, file=discord.File(file_path))

    @staticmethod
    async def _send_chunks(channel: discord.abc.Messageable, text: str) -> None:
        """Split long text into chunks that fit Discord's message limit."""
        while text:
            if len(text) <= DISCORD_MSG_LIMIT:
                await channel.send(text)
                return
            # Try to split at the last newline within the limit.
            cut = text.rfind("\n", 0, DISCORD_MSG_LIMIT)
            if cut == -1:
                cut = DISCORD_MSG_LIMIT
            await channel.send(text[:cut])
            text = text[cut:].lstrip("\n")
