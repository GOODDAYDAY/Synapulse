import logging

from apps.bot.provider.base import BaseProvider

logger = logging.getLogger("synapulse.provider.mock")


class Provider(BaseProvider):

    async def chat(self, message: str) -> str:
        logger.debug("Mock chat called (length=%d)", len(message))
        return "mock hello"
