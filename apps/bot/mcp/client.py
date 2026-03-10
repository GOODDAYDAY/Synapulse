"""MCP client manager — connect to MCP servers, discover tools, dispatch calls.

Manages the lifecycle of MCP server connections via stdio transport.
Each server runs as a subprocess; tools are discovered via the MCP protocol
and wrapped into format-compatible objects for the AI provider.
"""

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger("synapulse.mcp")

_DEFAULT_TIMEOUT_MS = 30000


@dataclass
class MCPToolWrapper:
    """Wrap an MCP tool definition for AI provider integration.

    Implements to_openai() and to_anthropic() via duck typing — same interface
    as native tools, without inheriting BaseTool.
    """

    name: str
    description: str
    parameters: dict
    usage_hint: str = ""
    server_name: str = ""

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


@dataclass
class _ServerEntry:
    """Internal record for an active MCP server connection."""

    name: str
    session: ClientSession
    tools: list[MCPToolWrapper] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    source: str = "dynamic"  # "static" or "dynamic"
    # Keep reference to exit stack for cleanup
    _stack: AsyncExitStack | None = None


class MCPManager:
    """Manage MCP server connections, tool discovery, and tool execution."""

    def __init__(self) -> None:
        self._servers: dict[str, _ServerEntry] = {}
        self._tool_index: dict[str, str] = {}  # tool_name → server_name

    async def connect(
            self,
            name: str,
            config: dict,
            source: str = "dynamic",
            native_tool_names: set[str] | None = None,
    ) -> list[str]:
        """Connect to an MCP server, discover its tools, return tool names.

        Args:
            name: Unique server identifier.
            config: Server config with command, args, env, timeout.
            source: "static" or "dynamic" (for disconnect behavior).
            native_tool_names: Set of native tool names to check for collisions.

        Returns:
            List of discovered tool names (possibly prefixed to avoid collisions).

        Raises:
            Exception: If connection or initialization fails.
        """
        if name in self._servers:
            await self.disconnect(name)
            logger.info("Reconnecting to server: %s", name)

        timeout_ms = config.get("timeout", _DEFAULT_TIMEOUT_MS)
        timeout_s = timeout_ms / 1000

        server_params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env"),
        )

        stack = AsyncExitStack()
        try:
            # Spawn process and create session
            read_stream, write_stream = await asyncio.wait_for(
                stack.enter_async_context(stdio_client(server_params)),
                timeout=timeout_s,
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))

            await asyncio.wait_for(session.initialize(), timeout=timeout_s)
            logger.info("MCP server '%s' initialized", name)

            # Discover tools
            result = await asyncio.wait_for(session.list_tools(), timeout=timeout_s)
            mcp_tools = result.tools if result.tools else []

            # Wrap tools and handle name collisions
            all_existing = set(self._tool_index.keys())
            if native_tool_names:
                all_existing |= native_tool_names

            wrappers = []
            for tool in mcp_tools:
                tool_name = tool.name
                if tool_name in all_existing:
                    tool_name = f"mcp_{name}_{tool.name}"
                    logger.warning(
                        "Tool name collision: '%s' renamed to '%s'",
                        tool.name, tool_name,
                    )

                wrapper = MCPToolWrapper(
                    name=tool_name,
                    description=tool.description or f"MCP tool from {name}",
                    parameters=tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
                    usage_hint=f"MCP tool from server '{name}'",
                    server_name=name,
                )
                wrappers.append(wrapper)
                self._tool_index[tool_name] = name

            entry = _ServerEntry(
                name=name,
                session=session,
                tools=wrappers,
                config=config,
                source=source,
                _stack=stack,
            )
            self._servers[name] = entry

            tool_names = [w.name for w in wrappers]
            logger.info(
                "MCP server '%s' connected: %d tools discovered%s",
                name, len(wrappers),
                f" ({', '.join(tool_names[:5])}{'...' if len(tool_names) > 5 else ''})" if tool_names else "",
            )
            return tool_names

        except Exception:
            # Clean up on failure
            await stack.aclose()
            raise

    async def disconnect(self, name: str) -> bool:
        """Disconnect an MCP server and remove its tools.

        Returns True if the server was found and disconnected.
        """
        entry = self._servers.pop(name, None)
        if not entry:
            return False

        # Remove tools from index
        for tool in entry.tools:
            self._tool_index.pop(tool.name, None)

        # Close the connection
        if entry._stack:
            try:
                await entry._stack.aclose()
            except Exception:
                logger.exception("Error closing MCP server '%s'", name)

        logger.info("MCP server '%s' disconnected", name)
        return True

    async def disconnect_all(self) -> None:
        """Disconnect all MCP servers. Called on bot shutdown."""
        names = list(self._servers.keys())
        for name in names:
            await self.disconnect(name)
        logger.info("All MCP servers disconnected")

    def get_all_tools(self) -> list[MCPToolWrapper]:
        """Return all discovered MCP tools across all connected servers."""
        tools = []
        for entry in self._servers.values():
            tools.extend(entry.tools)
        return tools

    def get_tool_schema(self, tool_name: str) -> dict | None:
        """Return the JSON Schema parameters for a tool, or None if not found."""
        server_name = self._tool_index.get(tool_name)
        if not server_name:
            return None
        entry = self._servers.get(server_name)
        if not entry:
            return None
        for tool in entry.tools:
            if tool.name == tool_name:
                return tool.parameters
        return None

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool is provided by any connected MCP server."""
        return tool_name in self._tool_index

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call an MCP tool and return the text result.

        Args:
            tool_name: The tool name (possibly prefixed).
            arguments: Tool arguments as a dict.

        Returns:
            Text result from the tool execution.
        """
        server_name = self._tool_index.get(tool_name)
        if not server_name:
            return f"Error: MCP tool '{tool_name}' not found"

        entry = self._servers.get(server_name)
        if not entry:
            return f"Error: MCP server '{server_name}' is disconnected"

        # Resolve original tool name (strip prefix if added for collision)
        original_name = tool_name
        prefix = f"mcp_{server_name}_"
        if tool_name.startswith(prefix):
            original_name = tool_name[len(prefix):]

        try:
            result = await entry.session.call_tool(original_name, arguments)
        except Exception as e:
            logger.exception("MCP tool call failed: %s on server '%s'", tool_name, server_name)
            # Mark server as potentially broken
            return f"Error calling MCP tool '{tool_name}': {e}"

        # Extract text from result content
        texts = []
        if result.content:
            for item in result.content:
                if hasattr(item, "text"):
                    texts.append(item.text)
                else:
                    texts.append(str(item))

        return "\n".join(texts) if texts else "(no output)"

    def list_servers(self) -> list[dict]:
        """Return summary info for all connected servers."""
        servers = []
        for entry in self._servers.values():
            servers.append({
                "name": entry.name,
                "source": entry.source,
                "tool_count": len(entry.tools),
                "tools": [t.name for t in entry.tools],
            })
        return servers

    def list_tools(self, server_name: str | None = None) -> list[dict]:
        """Return tool details for a specific server or all servers."""
        result = []
        entries = [
            self._servers[server_name]] if server_name and server_name in self._servers else self._servers.values()
        for entry in entries:
            for tool in entry.tools:
                result.append({
                    "name": tool.name,
                    "description": tool.description,
                    "server": entry.name,
                })
        return result


def load_mcp_config(path: str) -> dict:
    """Load MCP server config from a JSON file.

    Returns empty dict on missing or invalid file.
    Expected format: {"mcpServers": {"name": {"command": ..., "args": [...]}}}
    """
    config_path = Path(path)
    if not config_path.exists():
        logger.debug("MCP config not found: %s", path)
        return {}

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if not isinstance(servers, dict):
            logger.warning("Invalid mcpServers in %s (not an object), skipping", path)
            return {}
        logger.info("Loaded MCP config from %s: %d server(s)", path, len(servers))
        return servers
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in MCP config %s: %s", path, e)
        return {}
    except Exception:
        logger.exception("Failed to read MCP config: %s", path)
        return {}


def save_dynamic_config(path: str, servers: dict) -> None:
    """Persist dynamic MCP server configs to a JSON file.

    Writes atomically via temp file + rename.
    """
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = {"mcpServers": servers}
    tmp_path = config_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(config_path)
        logger.debug("Saved dynamic MCP config: %d server(s)", len(servers))
    except Exception:
        logger.exception("Failed to save dynamic MCP config to %s", path)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
