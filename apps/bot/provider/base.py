"""Base class for all AI provider implementations."""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("synapulse.provider")


class BaseProvider(ABC):

    def authenticate(self) -> None:
        """Override for providers that need authentication at startup."""
        logger.debug("%s requires no authentication", type(self).__name__)

    @abstractmethod
    async def chat(self, message: str) -> str:
        """Send a message to the AI and return the reply."""
