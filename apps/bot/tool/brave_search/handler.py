"""Brave Search tool — web search via Brave Search API."""

import logging

import aiohttp

from apps.bot.config.settings import config
from apps.bot.tool.base import AnthropicTool, OpenAITool

logger = logging.getLogger("synapulse.tool.brave_search")

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class Tool(OpenAITool, AnthropicTool):
    name = "brave_search"
    description = (
        "Search the web for current information. "
        "Use this when the user asks about recent events, real-time data, "
        "or anything you are unsure about."
    )
    usage_hint = "Current events, real-time data, or facts you're unsure about."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
        },
        "required": ["query"],
    }

    def validate(self) -> None:
        if not config.BRAVE_API_KEY:
            raise EnvironmentError(
                "BRAVE_API_KEY is required for brave_search tool. "
                "Get yours at https://brave.com/search/api/"
            )

    async def execute(self, query: str) -> str:
        logger.info("Searching: %s", query)
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": config.BRAVE_API_KEY,
        }
        params = {"q": query, "count": 5}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(SEARCH_URL, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error("Brave Search error %d: %s", resp.status, text[:200])
                        return f"Search failed ({resp.status})"
                    data = await resp.json()
        except Exception:
            logger.exception("Brave Search request failed")
            return "Search request failed"

        results = data.get("web", {}).get("results", [])
        if not results:
            return "No results found."

        lines = []
        for r in results[:5]:
            title = r.get("title", "")
            desc = r.get("description", "")
            url = r.get("url", "")
            lines.append(f"- {title}: {desc}\n  {url}")
        return "\n".join(lines)
