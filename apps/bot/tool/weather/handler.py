"""Weather tool — current weather and forecast via OpenWeatherMap API."""

import logging
from datetime import datetime, timezone

from apps.bot.config.settings import config
from apps.bot.tool.base import AnthropicTool, OpenAITool

logger = logging.getLogger("synapulse.tool.weather")

_BASE_URL = "https://api.openweathermap.org/data/2.5"


class Tool(OpenAITool, AnthropicTool):
    name = "weather"
    description = (
        "Get current weather and 3-day forecast for a location. "
        "Supports city names and coordinates. "
        "Examples: 'Beijing', 'Tokyo', 'New York', '40.7,-74.0'."
    )
    usage_hint = "Weather queries: current conditions, temperature, forecast."
    parameters = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name or coordinates (e.g. 'Shanghai', '31.2,121.5')",
            },
        },
        "required": ["location"],
    }

    def validate(self) -> None:
        if not config.OPENWEATHER_API_KEY:
            raise EnvironmentError(
                "OPENWEATHER_API_KEY is required for weather tool. "
                "Get yours at https://openweathermap.org/api"
            )

    async def execute(self, location: str) -> str:
        import aiohttp

        logger.info("Weather query: %s", location)
        api_key = config.OPENWEATHER_API_KEY
        params = _build_params(location, api_key)

        try:
            async with aiohttp.ClientSession() as session:
                # Current weather
                async with session.get(
                        f"{_BASE_URL}/weather", params=params,
                        timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error("OpenWeatherMap error %d: %s", resp.status, text[:200])
                        return f"Weather query failed (HTTP {resp.status})"
                    current = await resp.json()

                # 5-day forecast (use same params)
                async with session.get(
                        f"{_BASE_URL}/forecast", params={**params, "cnt": 24},
                        timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    forecast = await resp.json() if resp.status == 200 else {}

        except Exception:
            logger.exception("Weather request failed for '%s'", location)
            return "Weather request failed"

        return _format_weather(current, forecast)


def _build_params(location: str, api_key: str) -> dict:
    """Build API params — detect coordinate format vs city name."""
    base = {"appid": api_key, "units": "metric", "lang": "zh_cn"}

    # Check if location looks like coordinates (e.g. "31.2,121.5")
    parts = location.replace(" ", "").split(",")
    if len(parts) == 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            return {**base, "lat": lat, "lon": lon}
        except ValueError:
            pass

    return {**base, "q": location}


def _format_weather(current: dict, forecast: dict) -> str:
    """Format OpenWeatherMap JSON responses into readable text."""
    lines = []

    # Current conditions
    name = current.get("name", "?")
    country = current.get("sys", {}).get("country", "")
    main = current.get("main", {})
    weather = current.get("weather", [{}])[0]
    wind = current.get("wind", {})
    visibility = current.get("visibility")

    desc = weather.get("description", "")
    temp = main.get("temp", "?")
    feels = main.get("feels_like", "?")
    humidity = main.get("humidity", "?")
    temp_min = main.get("temp_min", "?")
    temp_max = main.get("temp_max", "?")
    wind_speed = wind.get("speed", "?")

    loc_label = f"{name}, {country}" if country else name
    lines.append(f"📍 {loc_label}")
    lines.append(f"Current: {desc}, {temp}°C (feels like {feels}°C)")
    lines.append(f"Range: {temp_min}~{temp_max}°C | Humidity: {humidity}%")
    lines.append(f"Wind: {wind_speed}m/s" + (f" | Visibility: {visibility / 1000:.1f}km" if visibility else ""))

    # Sunrise/sunset
    sys_data = current.get("sys", {})
    tz_offset = current.get("timezone", 0)
    sunrise = sys_data.get("sunrise")
    sunset = sys_data.get("sunset")
    if sunrise and sunset:
        sr = datetime.fromtimestamp(sunrise + tz_offset, tz=timezone.utc).strftime("%H:%M")
        ss = datetime.fromtimestamp(sunset + tz_offset, tz=timezone.utc).strftime("%H:%M")
        lines.append(f"Sunrise: {sr} | Sunset: {ss}")

    # Forecast — aggregate by date
    forecast_list = forecast.get("list", [])
    if forecast_list:
        lines.append("")
        lines.append("Forecast:")
        daily = _aggregate_daily(forecast_list, tz_offset)
        for date_str, day in list(daily.items())[:3]:
            desc = day["desc"]
            lines.append(f"  {date_str}: {desc}, {day['min']:.0f}~{day['max']:.0f}°C")

    return "\n".join(lines)


def _aggregate_daily(forecast_list: list, tz_offset: int) -> dict:
    """Aggregate 3-hour forecast entries into daily min/max/description."""
    daily: dict[str, dict] = {}

    for entry in forecast_list:
        dt = entry.get("dt", 0)
        local_dt = datetime.fromtimestamp(dt + tz_offset, tz=timezone.utc)
        date_str = local_dt.strftime("%Y-%m-%d")

        temp = entry.get("main", {}).get("temp", 0)
        desc = entry.get("weather", [{}])[0].get("description", "")

        if date_str not in daily:
            daily[date_str] = {"min": temp, "max": temp, "desc": desc, "noon_dist": 99}

        day = daily[date_str]
        day["min"] = min(day["min"], temp)
        day["max"] = max(day["max"], temp)

        # Pick description closest to noon (12:00) for the day's summary
        hour = local_dt.hour
        noon_dist = abs(hour - 12)
        if noon_dist < day["noon_dist"]:
            day["noon_dist"] = noon_dist
            day["desc"] = desc

    return daily
