"""Dynamic loading — scan directories, import modules, format tools."""

import importlib
import logging
from pathlib import Path

from apps.bot.job.base import BaseJob

logger = logging.getLogger("synapulse.core")


def scan_tools() -> dict:
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


def format_tool_hints(tools: dict) -> str:
    """Build per-tool routing hints for the system prompt from usage_hint attributes."""
    lines = []
    for tool in tools.values():
        hint = tool.usage_hint or tool.description
        lines.append(f"- {tool.name}: {hint}")
    return "\n".join(lines)


def format_tools_for_provider(tools: dict, api_format: str) -> list[dict]:
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


def merge_tools_for_provider(
        native_tools: dict,
        mcp_tools: list,
        api_format: str,
) -> list[dict]:
    """Merge native tools and MCP tool wrappers into one provider-formatted list.

    MCP tool wrappers implement the same to_openai()/to_anthropic() interface
    via duck typing, so they are formatted identically.
    """
    formatted = format_tools_for_provider(native_tools, api_format)
    method_name = f"to_{api_format}"
    for wrapper in mcp_tools:
        method = getattr(wrapper, method_name, None)
        if method:
            formatted.append(method())
        else:
            logger.warning("MCP tool %s doesn't support format: %s", wrapper.name, api_format)
    return formatted


def merge_tool_hints(native_tools: dict, mcp_tools: list) -> str:
    """Build combined tool hints for system prompt from native tools and MCP tools."""
    lines = []
    for tool in native_tools.values():
        hint = tool.usage_hint or tool.description
        lines.append(f"- {tool.name}: {hint}")
    for wrapper in mcp_tools:
        hint = wrapper.usage_hint or wrapper.description
        lines.append(f"- {wrapper.name}: {hint}")
    return "\n".join(lines)


def scan_jobs() -> list[BaseJob]:
    """Auto-scan job/ subfolders and load all valid Job classes."""
    job_dir = Path(__file__).resolve().parent.parent / "job"
    if not job_dir.is_dir():
        return []

    jobs = []
    for entry in sorted(job_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        handler = entry / "handler.py"
        if not handler.exists():
            continue
        try:
            mod = importlib.import_module(f"apps.bot.job.{entry.name}.handler")
            job = mod.Job()
            jobs.append(job)
            logger.info("Job discovered: %s", job.name)
        except Exception as e:
            logger.warning("Job skipped: %s (%s)", entry.name, e)
    return jobs
