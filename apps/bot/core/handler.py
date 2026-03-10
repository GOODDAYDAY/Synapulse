"""Bootstrap orchestrator — wire provider, tools, jobs, memory, and channel."""

import asyncio
import importlib
import logging

from apps.bot.config.settings import config
from apps.bot.core.loader import format_tools_for_provider, scan_jobs, scan_tools
from apps.bot.core.mention import make_mention_handler
from apps.bot.core.reminder import start_reminder_checker
from apps.bot.memory.database import Database

logger = logging.getLogger("synapulse.core")


async def start() -> None:
    """Bootstrap the bot: config → db → provider → tools → channel + jobs + reminders."""
    config.log_summary()

    # Init persistent storage
    db = Database()
    await db.init(config.DATABASE_PATH)

    # Init provider — authenticate() handles its own validation
    provider_module = importlib.import_module(f"apps.bot.provider.{config.AI_PROVIDER}.chat")
    provider = provider_module.Provider()
    provider.authenticate()
    logger.info("AI provider ready: %s", config.AI_PROVIDER)

    # Scan tools, inject db, format for provider's API
    tools = scan_tools()
    if tools:
        # Inject database into tools that need persistence (memo, reminder)
        for tool in tools.values():
            tool.db = db

        provider.tools = format_tools_for_provider(tools, provider.api_format)
        logger.info("Tools ready: %s", ", ".join(tools.keys()))
    else:
        logger.info("No tools loaded")

    # Scan jobs, inject summarize callback
    jobs = scan_jobs()

    async def summarize(prompt: str, text: str) -> str:
        messages = provider.build_messages(prompt, text)
        response = await provider.chat(messages)
        return response.text or "..."

    for job in jobs:
        job.summarize = summarize

    # Init channel — validate() handles its own config checks
    channel_module = importlib.import_module(f"apps.bot.channel.{config.CHANNEL_TYPE}.client")
    channel = channel_module.Channel()
    channel.validate()
    logger.info("Starting with channel=%s, ai=%s", config.CHANNEL_TYPE, config.AI_PROVIDER)

    # Core owns the event loop: channel task + job tasks + reminder checker
    channel_task = asyncio.create_task(
        channel.run(on_mention=make_mention_handler(provider, tools, channel.send_file, db))
    )
    await channel.wait_until_ready()

    # Start reminder checker (background task polling for due reminders)
    asyncio.create_task(start_reminder_checker(db, channel.send))
    logger.info("Reminder checker started")

    # Start all discovered jobs (each job self-manages enabled/disabled via jobs.json)
    if jobs:
        for job in jobs:
            asyncio.create_task(job.start(channel.send))
        logger.info("Jobs started: %s", ", ".join(j.name for j in jobs))
    else:
        logger.info("No jobs discovered")

    await channel_task
