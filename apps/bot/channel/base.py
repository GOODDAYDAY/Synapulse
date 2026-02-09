"""Base class for all channel implementations."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any, TypeAlias

# Callback type: (content, history) -> reply
MentionHandler: TypeAlias = Callable[
    [str, list[dict[str, str]] | None],
    Coroutine[Any, Any, str],
]


class BaseChannel(ABC):

    def validate(self) -> None:
        """Override to validate channel-specific config before starting."""

    @abstractmethod
    async def run(self, on_mention: MentionHandler) -> None:
        """Start listening and call on_mention when triggered."""

    @abstractmethod
    async def wait_until_ready(self) -> None:
        """Block until the channel is connected and ready to send."""

    @abstractmethod
    async def send(self, channel_id: str, message: str) -> None:
        """Send a message to the given channel."""
