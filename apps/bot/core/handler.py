"""
Core orchestrator — the brain of the bot.

Responsibilities:
- Load and initialize provider and channel based on .env config
- Scan and load tools from tool/ directory
- Format tools for the provider's API and set on provider
- Each implementation validates its own config (no central if-else)
- Inject handle_mention callback into channel
- Build prompt context, call provider, orchestrate tool-call loop
"""

import importlib
import logging
from pathlib import Path

from apps.bot.config.prompts import SYSTEM_PROMPT
from apps.bot.config.settings import config
from apps.bot.provider.base import BaseProvider

logger = logging.getLogger("synapulse.core")

_provider: BaseProvider | None = None
_tools: dict = {}

MAX_TOOL_ROUNDS = 10


def _scan_tools() -> dict:
    """Auto-scan tool/ subfolders and load all valid Tool classes."""
    tool_dir = Path(__file__).resolve().parent.parent / "tool"
    if not tool_dir.is_dir():
        return {}

    tools = {}
    for entry in sorted(tool_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        handler = entry / "handler.py"
        if not handler.exists():
            continue
        try:
            mod = importlib.import_module(f"apps.bot.tool.{entry.name}.handler")
            tool = mod.Tool()
            tool.validate()
            tools[tool.name] = tool
            logger.info("Tool loaded: %s", tool.name)
        except Exception as e:
            logger.warning("Tool skipped: %s (%s)", entry.name, e)
    return tools


def _format_tools_for_provider(tools: dict, api_format: str) -> list[dict]:
    """Convert tools to the provider's API format via tool.to_{api_format}()."""
    method_name = f"to_{api_format}"
    formatted = []
    for tool in tools.values():
        method = getattr(tool, method_name, None)
        if method:
            formatted.append(method())
        else:
            logger.warning("Tool %s doesn't support format: %s", tool.name, api_format)
    return formatted


async def handle_mention(
    content: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Process an @mention: build context, call provider, orchestrate tool-call loop."""
    logger.info("Handling mention (length=%d, history=%d)", len(content), len(history or []))

    # Build user prompt from content + history
    if history:
        context = "\n".join(f"{m['author']}: {m['content']}" for m in history)
        user_prompt = f"[Recent channel messages]\n{context}\n\n[User message]\n{content}"
    else:
        user_prompt = content

    messages = _provider.build_messages(SYSTEM_PROMPT, user_prompt)

    # Tool-call loop: core orchestrates, provider formats messages
    for _ in range(MAX_TOOL_ROUNDS):
        response = await _provider.chat(messages)

        if not response.tool_calls:
            logger.debug("Reply generated (length=%d)", len(response.text or ""))
            return response.text or "..."

        for call in response.tool_calls:
            tool = _tools.get(call.name)
            if not tool:
                logger.warning("Unknown tool requested: %s", call.name)
                _provider.append_tool_result(messages, call, f"Error: unknown tool '{call.name}'")
                continue

            logger.info("Executing tool: %s(%s)", call.name, call.arguments)
            try:
                result = await tool.execute(**call.arguments)
            except Exception as e:
                logger.exception("Tool execution failed: %s", call.name)
                result = f"Error: {e}"
            _provider.append_tool_result(messages, call, result)

    logger.warning("Tool-call loop hit max rounds (%d)", MAX_TOOL_ROUNDS)
    return "Sorry, I got stuck in a loop. Please try again."


def start() -> None:
    """Bootstrap the bot: config → provider → tools → channel."""
    global _provider, _tools

    config.log_summary()

    # Init provider — authenticate() handles its own validation
    provider_module = importlib.import_module(f"apps.bot.provider.{config.AI_PROVIDER}.chat")
    _provider = provider_module.Provider()
    _provider.authenticate()
    logger.info("AI provider ready: %s", config.AI_PROVIDER)

    # Scan tools, format for provider's API, set on provider
    _tools = _scan_tools()
    if _tools:
        _provider.tools = _format_tools_for_provider(_tools, _provider.api_format)
        logger.info("Tools ready: %s", ", ".join(_tools.keys()))
    else:
        logger.info("No tools loaded")

    # Init channel — validate() handles its own config checks
    channel_module = importlib.import_module(f"apps.bot.channel.{config.CHANNEL_TYPE}.client")
    channel = channel_module.Channel()
    channel.validate()
    logger.info("Starting with channel=%s, ai=%s", config.CHANNEL_TYPE, config.AI_PROVIDER)
    channel.run(on_mention=handle_mention)
