"""Tests for MCP client manager, tool wrapper, and mcp_server tool — covers REQ-004."""

import json
import os
import tempfile

import pytest

from apps.bot.mcp.client import MCPManager, MCPToolWrapper, load_mcp_config, save_dynamic_config


# --- MCPToolWrapper tests ---


def test_tool_wrapper_to_openai():
    wrapper = MCPToolWrapper(
        name="test_tool",
        description="A test tool",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    result = wrapper.to_openai()
    assert result["type"] == "function"
    assert result["function"]["name"] == "test_tool"
    assert result["function"]["description"] == "A test tool"
    assert "query" in result["function"]["parameters"]["properties"]


def test_tool_wrapper_to_anthropic():
    wrapper = MCPToolWrapper(
        name="test_tool",
        description="A test tool",
        parameters={"type": "object", "properties": {}},
    )
    result = wrapper.to_anthropic()
    assert result["name"] == "test_tool"
    assert result["description"] == "A test tool"
    assert result["input_schema"] == {"type": "object", "properties": {}}


# --- Config loading tests ---


def test_load_mcp_config_valid():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"mcpServers": {"test": {"command": "echo", "args": ["hello"]}}}, f)
        f.flush()
        config = load_mcp_config(f.name)
    os.unlink(f.name)
    assert "test" in config
    assert config["test"]["command"] == "echo"


def test_load_mcp_config_missing_file():
    config = load_mcp_config("/nonexistent/path/mcp.json")
    assert config == {}


def test_load_mcp_config_invalid_json():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("not json")
        f.flush()
        config = load_mcp_config(f.name)
    os.unlink(f.name)
    assert config == {}


def test_load_mcp_config_empty_servers():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"mcpServers": {}}, f)
        f.flush()
        config = load_mcp_config(f.name)
    os.unlink(f.name)
    assert config == {}


def test_load_mcp_config_invalid_servers_type():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"mcpServers": "not a dict"}, f)
        f.flush()
        config = load_mcp_config(f.name)
    os.unlink(f.name)
    assert config == {}


# --- save_dynamic_config tests ---


def test_save_dynamic_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "mcp_servers.json")
        servers = {"github": {"command": "npx", "args": ["-y", "@mcp/server-github"]}}
        save_dynamic_config(path, servers)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["mcpServers"]["github"]["command"] == "npx"


def test_save_dynamic_config_creates_parent_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "sub", "dir", "mcp_servers.json")
        save_dynamic_config(path, {"test": {"command": "echo"}})
        assert os.path.exists(path)


# --- MCPManager unit tests (no actual MCP servers) ---


def test_manager_initial_state():
    mgr = MCPManager()
    assert mgr.get_all_tools() == []
    assert mgr.list_servers() == []
    assert mgr.list_tools() == []
    assert not mgr.has_tool("any_tool")


def test_manager_get_tool_schema_not_found():
    mgr = MCPManager()
    assert mgr.get_tool_schema("nonexistent") is None


@pytest.mark.asyncio
async def test_manager_call_tool_not_found():
    mgr = MCPManager()
    result = await mgr.call_tool("nonexistent", {})
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_manager_disconnect_nonexistent():
    mgr = MCPManager()
    result = await mgr.disconnect("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_manager_disconnect_all_empty():
    mgr = MCPManager()
    await mgr.disconnect_all()  # Should not raise


# --- MCP server tool tests ---


@pytest.mark.asyncio
async def test_mcp_tool_no_manager():
    from apps.bot.tool.mcp_server.handler import Tool
    tool = Tool()
    result = await tool.execute(action="list")
    assert "not available" in result.lower()


@pytest.mark.asyncio
async def test_mcp_tool_list_empty():
    from apps.bot.tool.mcp_server.handler import Tool
    tool = Tool()
    tool.mcp_manager = MCPManager()
    result = await tool.execute(action="list")
    assert "no mcp servers" in result.lower()


@pytest.mark.asyncio
async def test_mcp_tool_list_tools_empty():
    from apps.bot.tool.mcp_server.handler import Tool
    tool = Tool()
    tool.mcp_manager = MCPManager()
    result = await tool.execute(action="list_tools")
    assert "no mcp tools" in result.lower()


@pytest.mark.asyncio
async def test_mcp_tool_add_missing_name():
    from apps.bot.tool.mcp_server.handler import Tool
    tool = Tool()
    tool.mcp_manager = MCPManager()
    result = await tool.execute(action="add", command="echo")
    assert "name is required" in result.lower()


@pytest.mark.asyncio
async def test_mcp_tool_add_missing_command():
    from apps.bot.tool.mcp_server.handler import Tool
    tool = Tool()
    tool.mcp_manager = MCPManager()
    result = await tool.execute(action="add", name="test")
    assert "command is required" in result.lower()


@pytest.mark.asyncio
async def test_mcp_tool_add_invalid_name():
    from apps.bot.tool.mcp_server.handler import Tool
    tool = Tool()
    tool.mcp_manager = MCPManager()
    result = await tool.execute(action="add", name="invalid name!", command="echo")
    assert "alphanumeric" in result.lower()


@pytest.mark.asyncio
async def test_mcp_tool_remove_not_connected():
    from apps.bot.tool.mcp_server.handler import Tool
    tool = Tool()
    tool.mcp_manager = MCPManager()
    result = await tool.execute(action="remove", name="nonexistent")
    assert "not connected" in result.lower()


@pytest.mark.asyncio
async def test_mcp_tool_unknown_action():
    from apps.bot.tool.mcp_server.handler import Tool
    tool = Tool()
    tool.mcp_manager = MCPManager()
    result = await tool.execute(action="unknown")
    assert "unknown action" in result.lower()


# --- Loader merge tests ---


def test_merge_tools_for_provider():
    from apps.bot.core.loader import merge_tools_for_provider

    class FakeTool:
        name = "native"
        description = "A native tool"
        parameters = {}
        usage_hint = ""

        def to_openai(self):
            return {"type": "function",
                    "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}

    native = {"native": FakeTool()}
    mcp = [MCPToolWrapper(name="mcp_tool", description="An MCP tool", parameters={"type": "object", "properties": {}})]

    result = merge_tools_for_provider(native, mcp, "openai")
    assert len(result) == 2
    names = [r["function"]["name"] for r in result]
    assert "native" in names
    assert "mcp_tool" in names


def test_merge_tool_hints():
    from apps.bot.core.loader import merge_tool_hints

    class FakeTool:
        name = "search"
        description = "Search the web"
        usage_hint = "Search for anything"

    native = {"search": FakeTool()}
    mcp = [MCPToolWrapper(name="github", description="GitHub tools", parameters={}, usage_hint="Manage GitHub")]

    result = merge_tool_hints(native, mcp)
    assert "search: Search for anything" in result
    assert "github: Manage GitHub" in result
