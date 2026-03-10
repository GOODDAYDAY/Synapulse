"""Tests for brave_search tool — validate, execute, result formatting."""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bot.tool.brave_search.handler import Tool


@pytest.fixture
def tool():
    return Tool()


# --- Fake aiohttp for tests (real aiohttp may not be installed) ---

def _make_fake_aiohttp(status=200, json_data=None, text_data="error"):
    """Create a fake aiohttp module with a mock ClientSession."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text_data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)

    session = AsyncMock()
    session.get = MagicMock(return_value=resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    fake = types.ModuleType("aiohttp")
    fake.ClientSession = MagicMock(return_value=session)
    return fake


# --- validate ---

def test_validate_no_api_key(tool):
    """Should raise when BRAVE_API_KEY is empty."""
    with patch("apps.bot.tool.brave_search.handler.config") as mock_config:
        mock_config.BRAVE_API_KEY = ""
        with pytest.raises(EnvironmentError, match="BRAVE_API_KEY"):
            tool.validate()


def test_validate_with_api_key(tool):
    """Should pass when BRAVE_API_KEY is set."""
    with patch("apps.bot.tool.brave_search.handler.config") as mock_config:
        mock_config.BRAVE_API_KEY = "test-key-123"
        tool.validate()


# --- tool metadata ---

def test_tool_name(tool):
    assert tool.name == "brave_search"


def test_tool_has_openai_format(tool):
    fmt = tool.to_openai()
    assert fmt["type"] == "function"
    assert fmt["function"]["name"] == "brave_search"
    assert "query" in fmt["function"]["parameters"]["properties"]


def test_tool_has_anthropic_format(tool):
    fmt = tool.to_anthropic()
    assert fmt["name"] == "brave_search"
    assert "query" in fmt["input_schema"]["properties"]


# --- execute ---

SAMPLE_RESULTS = {
    "web": {
        "results": [
            {"title": "Python Docs", "description": "Official Python documentation", "url": "https://docs.python.org"},
            {"title": "Real Python", "description": "Python tutorials", "url": "https://realpython.com"},
        ]
    }
}


@pytest.mark.asyncio
async def test_execute_success(tool):
    fake = _make_fake_aiohttp(200, SAMPLE_RESULTS)
    with patch.dict(sys.modules, {"aiohttp": fake}):
        with patch("apps.bot.tool.brave_search.handler.config") as mock_config:
            mock_config.BRAVE_API_KEY = "test-key"
            result = await tool.execute(query="python docs")

    assert "Python Docs" in result
    assert "Real Python" in result
    assert "https://docs.python.org" in result


@pytest.mark.asyncio
async def test_execute_no_results(tool):
    fake = _make_fake_aiohttp(200, {"web": {"results": []}})
    with patch.dict(sys.modules, {"aiohttp": fake}):
        with patch("apps.bot.tool.brave_search.handler.config") as mock_config:
            mock_config.BRAVE_API_KEY = "test-key"
            result = await tool.execute(query="asdfghjkl")

    assert result == "No results found."


@pytest.mark.asyncio
async def test_execute_http_error(tool):
    fake = _make_fake_aiohttp(403)
    with patch.dict(sys.modules, {"aiohttp": fake}):
        with patch("apps.bot.tool.brave_search.handler.config") as mock_config:
            mock_config.BRAVE_API_KEY = "test-key"
            result = await tool.execute(query="test")

    assert "Search failed (403)" in result


@pytest.mark.asyncio
async def test_execute_network_error(tool):
    fake = types.ModuleType("aiohttp")
    fake.ClientSession = MagicMock(side_effect=Exception("connection refused"))
    with patch.dict(sys.modules, {"aiohttp": fake}):
        with patch("apps.bot.tool.brave_search.handler.config") as mock_config:
            mock_config.BRAVE_API_KEY = "test-key"
            result = await tool.execute(query="test")

    assert result == "Search request failed"


@pytest.mark.asyncio
async def test_execute_limits_to_5_results(tool):
    many_results = {
        "web": {
            "results": [
                {"title": f"Result {i}", "description": f"Desc {i}", "url": f"https://example.com/{i}"}
                for i in range(10)
            ]
        }
    }
    fake = _make_fake_aiohttp(200, many_results)
    with patch.dict(sys.modules, {"aiohttp": fake}):
        with patch("apps.bot.tool.brave_search.handler.config") as mock_config:
            mock_config.BRAVE_API_KEY = "test-key"
            result = await tool.execute(query="test")

    assert result.count("- Result") == 5
    assert "Result 0" in result
    assert "Result 4" in result
    assert "Result 5" not in result
