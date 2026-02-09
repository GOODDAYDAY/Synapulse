import logging

import aiohttp

from apps.bot.config.prompts import SYSTEM_PROMPT
from apps.bot.config.settings import config
from apps.bot.provider.base import BaseProvider
from apps.bot.provider.copilot.auth import get_token

logger = logging.getLogger("synapulse.provider.copilot")

API_URL = "https://models.inference.ai.azure.com/chat/completions"


class Provider(BaseProvider):

    def authenticate(self) -> None:
        get_token()

    async def chat(self, message: str) -> str:
        token = get_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.AI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
        }

        logger.debug("Sending chat request (model=%s, length=%d)", config.AI_MODEL, len(message))

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(API_URL, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error("AI API error %d: %s", resp.status, text[:200])
                        return f"[AI Error {resp.status}] {text[:200]}"
                    data = await resp.json()
                    reply = data["choices"][0]["message"]["content"] or "..."
                    logger.debug("Chat response received (length=%d)", len(reply))
                    return reply
        except Exception:
            logger.exception("Unexpected error during AI chat request")
            return "[AI Error] Request failed"
