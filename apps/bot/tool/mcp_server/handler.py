"""MCP server management tool — add, remove, list dynamically added MCP servers.

Allows the AI to manage dynamic MCP server connections in response to user
requests. Dynamic servers are persisted to data/mcp_servers.json.

Pre-configured servers in mcp.json are managed by editing the config file
directly — the hot-reload loop detects changes and connects/disconnects
automatically.
"""

import logging
import re
from typing import Any

from apps.bot.tool.base import AnthropicTool, OpenAITool

logger = logging.getLogger("synapulse.tool.mcp_server")

_MAX_SERVERS = 20
_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")


class Tool(OpenAITool, AnthropicTool):
    name = "mcp_server"
    description = (
        "Manage MCP (Model Context Protocol) servers. "
        "Add new servers dynamically, remove them, or list connected servers and their tools."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "remove", "list", "list_tools"],
                "description": (
                    "Action to perform. "
                    "'add' connects a new MCP server process. "
                    "'remove' disconnects and removes a dynamically added server. "
                    "'list' shows connected servers. "
                    "'list_tools' shows tools from connected servers."
                ),
            },
            "name": {
                "type": "string",
                "description": "Server name. Alphanumeric and underscores only.",
            },
            "command": {
                "type": "string",
                "description": "Command to run the MCP server (for add), e.g. 'npx', 'uvx'",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command arguments (for add), e.g. ['-y', '@modelcontextprotocol/server-github']",
            },
            "env": {
                "type": "object",
                "description": "Environment variables for the server process (for add)",
            },
            "timeout": {
                "type": "integer",
                "description": "Connection timeout in milliseconds (for add, default 30000)",
            },
        },
        "required": ["action"],
    }
    usage_hint = (
        "Manage dynamic MCP tool servers: add/remove servers, list servers and their tools"
    )

    # Injected by core at startup
    mcp_manager: Any = None
    _rebuild_tools: Any = None  # Callback to rebuild provider tool list
    _dynamic_config_path: str = ""  # Path to data/mcp_servers.json

    def validate(self) -> None:
        # mcp_manager is injected by core after scan_tools(), so not available here.
        pass

    async def execute(self, action: str, **kwargs) -> str:
        if not self.mcp_manager:
            return "Error: MCP manager not available"

        if action == "add":
            return await self._add(**kwargs)
        if action == "remove":
            return await self._remove(**kwargs)
        if action == "list":
            return self._list()
        if action == "list_tools":
            return self._list_tools(**kwargs)

        return f"Error: unknown action '{action}'"

    async def _add(
            self,
            name: str = "",
            command: str = "",
            args: list[str] | None = None,
            env: dict | None = None,
            timeout: int = 30000,
            **_: Any,
    ) -> str:
        if not name:
            return "Error: server name is required"
        if not command:
            return "Error: command is required"
        if not _NAME_PATTERN.match(name):
            return "Error: server name must be alphanumeric and underscores only"

        # Check server limit
        current_count = len(self.mcp_manager.list_servers())
        if current_count >= _MAX_SERVERS:
            return f"Error: maximum {_MAX_SERVERS} servers reached"

        config = {
            "enabled": True,
            "command": command,
            "args": args or [],
            "timeout": timeout,
        }
        if env:
            config["env"] = env

        try:
            tool_names = await self.mcp_manager.connect(name, config, source="dynamic")
        except Exception as e:
            logger.exception("Failed to connect MCP server '%s'", name)
            return f"Error connecting to server '{name}': {e}"

        # Persist to dynamic config
        self._persist_dynamic_config()

        # Rebuild provider tool list
        if self._rebuild_tools:
            self._rebuild_tools()

        if tool_names:
            return (
                f"Connected server '{name}'. Discovered {len(tool_names)} tool(s): "
                f"{', '.join(tool_names[:10])}"
                f"{'...' if len(tool_names) > 10 else ''}"
            )
        return f"Connected server '{name}', but it provides no tools."

    async def _remove(self, name: str = "", **_: Any) -> str:
        if not name:
            return "Error: server name is required"

        # Check if server exists
        servers = {s["name"]: s for s in self.mcp_manager.list_servers()}
        if name not in servers:
            return f"Error: server '{name}' is not connected"

        server_info = servers[name]
        disconnected = await self.mcp_manager.disconnect(name)
        if not disconnected:
            return f"Error: failed to disconnect server '{name}'"

        # Remove from dynamic config (static servers just disconnect for this session)
        if server_info.get("source") == "dynamic":
            self._persist_dynamic_config()

        # Rebuild provider tool list
        if self._rebuild_tools:
            self._rebuild_tools()

        return f"Disconnected server '{name}'."

    def _list(self) -> str:
        servers = self.mcp_manager.list_servers()
        if not servers:
            return "No MCP servers connected."

        lines = []
        for s in servers:
            lines.append(f"- {s['name']} ({s['source']}): {s['tool_count']} tool(s)")
        return f"{len(servers)} MCP server(s) connected:\n" + "\n".join(lines)

    def _list_tools(self, name: str = "", **_: Any) -> str:
        tools = self.mcp_manager.list_tools(name if name else None)
        if not tools:
            if name:
                return f"No tools found for server '{name}' (server may not exist or has no tools)."
            return "No MCP tools available."

        lines = []
        for t in tools:
            lines.append(f"- {t['name']} ({t['server']}): {t['description']}")
        return f"{len(tools)} MCP tool(s):\n" + "\n".join(lines)

    def _persist_dynamic_config(self) -> None:
        """Save current dynamic server configs to disk."""
        if not self._dynamic_config_path:
            logger.warning("Dynamic config path not set, skipping persist")
            return

        from apps.bot.mcp.client import save_dynamic_config

        # Collect configs for dynamic servers only
        dynamic_servers = {}
        for s in self.mcp_manager.list_servers():
            if s["source"] == "dynamic":
                entry = self.mcp_manager._servers.get(s["name"])
                if entry:
                    dynamic_servers[s["name"]] = entry.config

        save_dynamic_config(self._dynamic_config_path, dynamic_servers)
