"""Base classes for all AI provider implementations.

BaseProvider defines the core contract (authenticate, chat).
Format classes (OpenAIProvider, AnthropicProvider, ...) add message formatting.
A concrete provider inherits from the format class matching its API.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger("synapulse.provider")


@dataclass
class ToolCall:
    """A tool invocation requested by the AI."""
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResponse:
    """Response from the AI — either final text or tool call requests."""
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class BaseProvider(ABC):
    """Core provider contract — all providers extend a format subclass of this."""

    api_format: str

    def __init__(self) -> None:
        self._tools: list[dict] = []

    @property
    def tools(self) -> list[dict]:
        """Pre-formatted tool definitions, set by core at startup."""
        return self._tools

    @tools.setter
    def tools(self, value: list[dict]) -> None:
        self._tools = value

    def authenticate(self) -> None:
        """Override for providers that need authentication at startup."""
        logger.debug("%s requires no authentication", type(self).__name__)

    @abstractmethod
    def build_messages(self, system_prompt: str, user_prompt: str) -> list:
        """Build initial messages in API format."""

    @abstractmethod
    def append_tool_result(self, messages: list, tool_call: ToolCall, result: str) -> None:
        """Append a tool execution result to messages."""

    @abstractmethod
    def parse_tool_calls(self, raw_msg: dict) -> list[ToolCall]:
        """Parse tool calls from a raw AI response message."""

    @abstractmethod
    def compress_tool_results(self, messages: list, threshold: int) -> None:
        """Replace consumed tool results exceeding threshold with a size note.

        Called by core after provider.chat() returns — at that point the AI has
        already processed all tool results in messages. Compressing them avoids
        re-sending large payloads on subsequent rounds.
        """

    @abstractmethod
    async def chat(self, messages: list, tool_choice: str | None = None) -> ChatResponse:
        """Send messages to AI. Appends assistant response to messages. Returns parsed response.

        tool_choice: optional hint passed to the API (e.g. "auto", "required", "none").
        Only takes effect when tools are loaded. Default None means provider default.
        """


class OpenAIProvider(BaseProvider):
    """Provider format for OpenAI-compatible APIs (GitHub Models, Azure OpenAI, etc.)."""

    api_format = "openai"

    def build_messages(self, system_prompt: str, user_prompt: str) -> list[dict]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def append_tool_result(self, messages: list, tool_call: ToolCall, result: str) -> None:
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result,
        })

    def parse_tool_calls(self, raw_msg: dict) -> list[ToolCall]:
        if not raw_msg.get("tool_calls"):
            return []
        return [
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"]["arguments"]),
            )
            for tc in raw_msg["tool_calls"]
        ]

    def compress_tool_results(self, messages: list, threshold: int) -> None:
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if len(content) > threshold:
                logger.debug("Compressing tool result: %d chars", len(content))
                msg["content"] = f"[Compressed result: {len(content)} chars]"


class AnthropicProvider(BaseProvider):
    """Provider format for Anthropic API."""

    api_format = "anthropic"

    def build_messages(self, system_prompt: str, user_prompt: str) -> list[dict]:
        return [
            {"role": "user", "content": user_prompt},
        ]

    def append_tool_result(self, messages: list, tool_call: ToolCall, result: str) -> None:
        messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_call.id, "content": result}],
        })

    def parse_tool_calls(self, raw_msg: dict) -> list[ToolCall]:
        content = raw_msg.get("content", [])
        if not isinstance(content, list):
            return []
        return [
            ToolCall(
                id=block["id"],
                name=block["name"],
                arguments=block.get("input", {}),
            )
            for block in content
            if block.get("type") == "tool_use"
        ]

    def compress_tool_results(self, messages: list, threshold: int) -> None:
        for msg in messages:
            if not isinstance(msg.get("content"), list):
                continue
            for block in msg["content"]:
                if block.get("type") != "tool_result":
                    continue
                content = block.get("content", "")
                if isinstance(content, str) and len(content) > threshold:
                    logger.debug("Compressing tool result: %d chars", len(content))
                    block["content"] = f"[Compressed result: {len(content)} chars]"
