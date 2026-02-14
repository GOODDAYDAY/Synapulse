"""Ollama provider — local AI via OpenAI-compatible endpoint."""

import logging

import aiohttp

from apps.bot.config.settings import config
from apps.bot.provider.base import ChatResponse, OpenAIProvider

logger = logging.getLogger("synapulse.provider.ollama")


class Provider(OpenAIProvider):

    def authenticate(self) -> None:
        if not config.OLLAMA_BASE_URL:
            raise RuntimeError("OLLAMA_BASE_URL is required for ollama provider")
        logger.info("Ollama endpoint: %s", config.OLLAMA_BASE_URL)

    async def chat(self, messages: list, tool_choice: str | None = None) -> ChatResponse:
        url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": config.AI_MODEL,
            "messages": messages,
        }
        if self.tools:
            payload["tools"] = self.tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        logger.debug("Sending chat request (model=%s, messages=%d)", config.AI_MODEL, len(messages))

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error("AI API error %d: %s", resp.status, text[:200])
                        return ChatResponse(text=f"[AI Error {resp.status}] {text[:200]}")
                    data = await resp.json()
        except Exception:
            logger.exception("Unexpected error during AI chat request")
            return ChatResponse(text="[AI Error] Request failed")

        msg = data["choices"][0]["message"]
        messages.append(msg)

        tool_calls = self.parse_tool_calls(msg)
        if tool_calls:
            logger.debug("AI requested %d tool call(s)", len(tool_calls))
            return ChatResponse(tool_calls=tool_calls)

        text = msg.get("content") or "..."
        logger.debug("Chat response received (length=%d)", len(text))
        return ChatResponse(text=text)
