"""Tests for weather tool — validate, execute, response formatting."""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bot.tool.weather.handler import Tool, _format_weather, _build_params, _aggregate_daily


@pytest.fixture
def tool():
    return Tool()


# --- Fake aiohttp for tests ---

def _make_fake_aiohttp(responses: list[tuple[int, dict]]):
    """Create a fake aiohttp module. responses is a list of (status, json) for sequential calls."""
    call_idx = [0]

    def _make_resp(status, json_data):
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(return_value=json_data)
        resp.text = AsyncMock(return_value="error")
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    def _get_side_effect(*args, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        status, data = responses[idx] if idx < len(responses) else (500, {})
        return _make_resp(status, data)

    session = AsyncMock()
    session.get = MagicMock(side_effect=_get_side_effect)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    fake = types.ModuleType("aiohttp")
    fake.ClientSession = MagicMock(return_value=session)
    fake.ClientTimeout = MagicMock(return_value=MagicMock())
    return fake


# --- Sample data ---

SAMPLE_CURRENT = {
    "name": "Singapore",
    "sys": {"country": "SG", "sunrise": 1710028800, "sunset": 1710072000},
    "timezone": 28800,
    "main": {"temp": 31, "feels_like": 35, "temp_min": 29, "temp_max": 33, "humidity": 75},
    "weather": [{"description": "多云", "main": "Clouds"}],
    "wind": {"speed": 3.5},
    "visibility": 10000,
}

SAMPLE_FORECAST = {
    "list": [
        {"dt": 1710050400, "main": {"temp": 30}, "weather": [{"description": "晴"}]},
        {"dt": 1710061200, "main": {"temp": 32}, "weather": [{"description": "多云"}]},
        {"dt": 1710072000, "main": {"temp": 28}, "weather": [{"description": "阵雨"}]},
        {"dt": 1710136800, "main": {"temp": 27}, "weather": [{"description": "雷阵雨"}]},
        {"dt": 1710147600, "main": {"temp": 31}, "weather": [{"description": "多云"}]},
        {"dt": 1710158400, "main": {"temp": 29}, "weather": [{"description": "晴"}]},
    ]
}


# --- tool metadata ---

def test_tool_name(tool):
    assert tool.name == "weather"


def test_tool_has_openai_format(tool):
    fmt = tool.to_openai()
    assert fmt["type"] == "function"
    assert fmt["function"]["name"] == "weather"
    assert "location" in fmt["function"]["parameters"]["properties"]


def test_tool_has_anthropic_format(tool):
    fmt = tool.to_anthropic()
    assert fmt["name"] == "weather"
    assert "location" in fmt["input_schema"]["properties"]


# --- validate ---

def test_validate_no_api_key(tool):
    with patch("apps.bot.tool.weather.handler.config") as mock_config:
        mock_config.OPENWEATHER_API_KEY = ""
        with pytest.raises(EnvironmentError, match="OPENWEATHER_API_KEY"):
            tool.validate()


def test_validate_with_api_key(tool):
    with patch("apps.bot.tool.weather.handler.config") as mock_config:
        mock_config.OPENWEATHER_API_KEY = "test-key"
        tool.validate()


# --- _build_params ---

def test_build_params_city_name():
    params = _build_params("Beijing", "key123")
    assert params["q"] == "Beijing"
    assert params["appid"] == "key123"
    assert params["units"] == "metric"


def test_build_params_coordinates():
    params = _build_params("31.2,121.5", "key123")
    assert params["lat"] == 31.2
    assert params["lon"] == 121.5
    assert "q" not in params


def test_build_params_coordinates_with_spaces():
    params = _build_params("40.7, -74.0", "key123")
    assert params["lat"] == 40.7
    assert params["lon"] == -74.0


def test_build_params_invalid_coordinates():
    """Non-numeric coordinate-like string should fall back to city name."""
    params = _build_params("New York,USA", "key123")
    assert params["q"] == "New York,USA"


# --- _format_weather ---

def test_format_weather_full():
    result = _format_weather(SAMPLE_CURRENT, SAMPLE_FORECAST)
    assert "Singapore, SG" in result
    assert "31°C" in result
    assert "feels like 35°C" in result
    assert "75%" in result
    assert "3.5m/s" in result
    assert "Sunrise:" in result
    assert "Forecast:" in result


def test_format_weather_no_forecast():
    result = _format_weather(SAMPLE_CURRENT, {})
    assert "Singapore" in result
    assert "Forecast:" not in result


def test_format_weather_minimal():
    minimal = {"name": "Test", "main": {}, "weather": [{}], "wind": {}}
    result = _format_weather(minimal, {})
    assert "Test" in result


# --- _aggregate_daily ---

def test_aggregate_daily_groups_by_date():
    daily = _aggregate_daily(SAMPLE_FORECAST["list"], 28800)
    assert len(daily) >= 1
    for date_str, day in daily.items():
        assert day["min"] <= day["max"]
        assert day["desc"]


# --- execute ---

@pytest.mark.asyncio
async def test_execute_success(tool):
    fake = _make_fake_aiohttp([(200, SAMPLE_CURRENT), (200, SAMPLE_FORECAST)])
    with patch.dict(sys.modules, {"aiohttp": fake}):
        with patch("apps.bot.tool.weather.handler.config") as mock_config:
            mock_config.OPENWEATHER_API_KEY = "test-key"
            result = await tool.execute(location="Singapore")

    assert "Singapore" in result
    assert "31°C" in result


@pytest.mark.asyncio
async def test_execute_current_fails(tool):
    fake = _make_fake_aiohttp([(401, {})])
    with patch.dict(sys.modules, {"aiohttp": fake}):
        with patch("apps.bot.tool.weather.handler.config") as mock_config:
            mock_config.OPENWEATHER_API_KEY = "bad-key"
            result = await tool.execute(location="Test")

    assert "Weather query failed" in result
    assert "401" in result


@pytest.mark.asyncio
async def test_execute_forecast_fails_gracefully(tool):
    """If forecast fails but current succeeds, should still return current weather."""
    fake = _make_fake_aiohttp([(200, SAMPLE_CURRENT), (500, {})])
    with patch.dict(sys.modules, {"aiohttp": fake}):
        with patch("apps.bot.tool.weather.handler.config") as mock_config:
            mock_config.OPENWEATHER_API_KEY = "test-key"
            result = await tool.execute(location="Singapore")

    assert "Singapore" in result
    assert "Forecast:" not in result


@pytest.mark.asyncio
async def test_execute_network_error(tool):
    fake = types.ModuleType("aiohttp")
    fake.ClientSession = MagicMock(side_effect=Exception("timeout"))
    fake.ClientTimeout = MagicMock(return_value=MagicMock())
    with patch.dict(sys.modules, {"aiohttp": fake}):
        with patch("apps.bot.tool.weather.handler.config") as mock_config:
            mock_config.OPENWEATHER_API_KEY = "test-key"
            result = await tool.execute(location="Test")

    assert result == "Weather request failed"
