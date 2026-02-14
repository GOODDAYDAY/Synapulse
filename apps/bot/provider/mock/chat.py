"""Mock provider — returns a fixed response for testing."""

import logging

from apps.bot.provider.base import ChatResponse, OpenAIProvider

logger = logging.getLogger("synapulse.provider.mock")


class Provider(OpenAIProvider):

    async def chat(self, messages: list, tool_choice: str | None = None) -> ChatResponse:
        logger.debug("Mock chat called (messages=%d)", len(messages))
        return ChatResponse(text="mock hello")
