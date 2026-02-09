"""Base class for all job implementations."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any, TypeAlias

logger = logging.getLogger("synapulse.job")

# Callback types injected by core
NotifyCallback: TypeAlias = Callable[[str, str], Coroutine[Any, Any, None]]
SummarizeCallback: TypeAlias = Callable[[str, str], Coroutine[Any, Any, str]]


class BaseJob(ABC):
    """Contract for all background jobs."""

    name: str
    prompt: str = ""
    summarize: SummarizeCallback | None = None

    def validate(self) -> None:
        """Override to validate job-specific secrets before running."""

    def format_for_ai(self, item: dict) -> str:
        """Convert an item to text for AI summarization."""
        return "\n".join(f"{k}: {v}" for k, v in item.items())

    def format_notification(self, item: dict, summary: str) -> str:
        """Format the final notification message."""
        return summary

    async def process(self, item: dict, prompt: str) -> str:
        """Turn an item into a notification message. Override to add AI summarization."""
        text = self.format_for_ai(item)
        return self.format_notification(item, text)

    @abstractmethod
    async def start(self, notify: NotifyCallback) -> None:
        """Run the job loop. Called as a background task."""
