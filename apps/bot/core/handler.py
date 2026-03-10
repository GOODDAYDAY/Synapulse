"""Bootstrap orchestrator — wire provider, tools, jobs, memory, MCP, and channel."""

import asyncio
import importlib
import logging
from pathlib import Path

from apps.bot.config.settings import config
from apps.bot.core.loader import (
    merge_tool_hints,
    merge_tools_for_provider,
    scan_jobs,
    scan_tools,
)
from apps.bot.core.mention import make_mention_handler
from apps.bot.core.reminder import start_reminder_checker
from apps.bot.mcp.client import MCPManager, load_mcp_config
from apps.bot.memory.database import Database

logger = logging.getLogger("synapulse.core")

# Config file paths
_STATIC_MCP_CONFIG = Path(__file__).resolve().parent.parent / "config" / "mcp.json"

# How often to check mcp.json for changes (seconds)
_MCP_RELOAD_INTERVAL = 30


def _get_enabled_servers(servers: dict) -> dict:
    """Filter server configs to only those with enabled=True (default True for backward compat)."""
    return {
        name: cfg for name, cfg in servers.items()
        if cfg.get("enabled", True) and name != "_comment"
    }


def _server_config_changed(old: dict, new: dict) -> bool:
    """Check if the meaningful parts of a server config have changed."""
    keys = ("command", "args", "env", "timeout")
    for k in keys:
        if old.get(k) != new.get(k):
            return True
    return False


async def _mcp_reload_loop(
        mcp_manager: MCPManager,
        static_config_path: str,
        dynamic_config_path: str,
        native_tool_names: set[str],
        rebuild_tools,
) -> None:
    """Background task: periodically re-read MCP configs and apply changes.

    Detects three types of changes:
    - New enabled servers → connect
    - Removed or disabled servers → disconnect
    - Config changed for existing server → reconnect
    """
    while True:
        await asyncio.sleep(_MCP_RELOAD_INTERVAL)
        try:
            static = load_mcp_config(static_config_path)
            dynamic = load_mcp_config(dynamic_config_path)
            merged = {**static, **dynamic}
            desired = _get_enabled_servers(merged)

            # Current state
            current_names = {s["name"] for s in mcp_manager.list_servers()}
            desired_names = set(desired.keys())

            # Servers to disconnect (removed or disabled)
            to_remove = current_names - desired_names
            # Servers to connect (newly enabled)
            to_add = desired_names - current_names
            # Servers that may have changed config
            to_check = current_names & desired_names

            for name in to_check:
                entry = mcp_manager._servers.get(name)
                if entry and _server_config_changed(entry.config, desired[name]):
                    to_remove.add(name)
                    to_add.add(name)

            if not to_remove and not to_add:
                continue

            changed = False
            for name in to_remove:
                logger.info("MCP hot-reload: disconnecting '%s'", name)
                await mcp_manager.disconnect(name)
                changed = True

            for name in to_add:
                source = "dynamic" if name in dynamic else "static"
                try:
                    logger.info("MCP hot-reload: connecting '%s'", name)
                    await mcp_manager.connect(
                        name, desired[name], source=source, native_tool_names=native_tool_names,
                    )
                    changed = True
                except Exception:
                    logger.exception("MCP hot-reload: failed to connect '%s'", name)

            if changed:
                rebuild_tools()
                logger.info("MCP hot-reload: applied changes (+%d -%d)", len(to_add), len(to_remove))

        except Exception:
            logger.exception("MCP hot-reload check failed")


async def start() -> None:
    """Bootstrap the bot: config → db → provider → tools → MCP → channel + jobs + reminders."""
    config.log_summary()

    # Init persistent storage
    db = Database()
    await db.init(config.DATABASE_PATH)

    # Init provider — authenticate() handles its own validation
    provider_module = importlib.import_module(f"apps.bot.provider.{config.AI_PROVIDER}.chat")
    provider = provider_module.Provider()
    provider.authenticate()
    logger.info("AI provider ready: %s", config.AI_PROVIDER)

    # Scan tools, inject db
    tools = scan_tools()
    if tools:
        for tool in tools.values():
            tool.db = db
        logger.info("Tools ready: %s", ", ".join(tools.keys()))
    else:
        logger.info("No tools loaded")

    # --- MCP setup ---
    mcp_manager = MCPManager()
    dynamic_config_path = str(Path(config.DATABASE_PATH).parent / "mcp_servers.json")
    static_config_path = str(_STATIC_MCP_CONFIG)

    # Load static + dynamic MCP configs
    static_servers = load_mcp_config(static_config_path)
    dynamic_servers = load_mcp_config(dynamic_config_path)

    # Merge: dynamic overrides static for same name
    overlap = set(static_servers) & set(dynamic_servers)
    for name in overlap:
        logger.warning("MCP server '%s' defined in both static and dynamic config, dynamic takes precedence", name)
    merged_servers = {**static_servers, **dynamic_servers}

    # Connect to enabled MCP servers
    native_tool_names = set(tools.keys())
    enabled_servers = _get_enabled_servers(merged_servers)
    for server_name, server_config in enabled_servers.items():
        source = "dynamic" if server_name in dynamic_servers else "static"
        try:
            await mcp_manager.connect(server_name, server_config, source=source, native_tool_names=native_tool_names)
        except Exception:
            logger.exception("MCP server '%s' failed to connect, skipping", server_name)
    if merged_servers:
        logger.info("MCP config: %d server(s) defined, %d enabled", len(merged_servers), len(enabled_servers))

    # Inject MCP manager into mcp_server tool
    mcp_tool = tools.get("mcp_server")
    if mcp_tool:
        mcp_tool.mcp_manager = mcp_manager
        mcp_tool._dynamic_config_path = dynamic_config_path

    # Build merged tool list (native + MCP) and update provider
    def rebuild_tools() -> None:
        """Rebuild provider tool list from native tools + MCP tools."""
        mcp_tools = mcp_manager.get_all_tools()
        provider.tools = merge_tools_for_provider(tools, mcp_tools, provider.api_format)
        # Update tool hints for mention handler
        nonlocal tool_hints
        tool_hints = merge_tool_hints(tools, mcp_tools)
        logger.info(
            "Tool list rebuilt: %d native + %d MCP = %d total",
            len(tools), len(mcp_tools), len(provider.tools),
        )

    tool_hints = ""
    rebuild_tools()

    # Inject rebuild callback into mcp_server tool
    if mcp_tool:
        mcp_tool._rebuild_tools = rebuild_tools

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
    try:
        channel_task = asyncio.create_task(
            channel.run(
                on_mention=make_mention_handler(
                    provider, tools, channel.send_file, db, mcp_manager,
                    tool_hints_ref=lambda: tool_hints,
                ),
            )
        )
        await channel.wait_until_ready()

        # Start reminder checker (background task polling for due reminders)
        asyncio.create_task(start_reminder_checker(db, channel.send))
        logger.info("Reminder checker started")

        # Start MCP config hot-reload watcher
        asyncio.create_task(_mcp_reload_loop(
            mcp_manager, static_config_path, dynamic_config_path,
            native_tool_names, rebuild_tools,
        ))
        logger.info("MCP hot-reload watcher started (interval=%ds)", _MCP_RELOAD_INTERVAL)

        # Start all discovered jobs (each job self-manages enabled/disabled via jobs.json)
        if jobs:
            for job in jobs:
                asyncio.create_task(job.start(channel.send))
            logger.info("Jobs started: %s", ", ".join(j.name for j in jobs))
        else:
            logger.info("No jobs discovered")

        await channel_task
    finally:
        # Cleanup MCP connections on shutdown
        await mcp_manager.disconnect_all()
