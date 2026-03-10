"""Base classes for all AI provider implementations.

BaseProvider defines the core contract (authenticate, chat).
Format classes (OpenAIProvider, AnthropicProvider) add message formatting
and rotation-aware chat() with automatic endpoint failover.

A concrete provider inherits from the format class matching its API.
Mock provider overrides chat() to skip HTTP entirely.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from apps.bot.config.models import EndpointConfig
from apps.bot.provider.endpoint import EndpointPool
from apps.bot.provider.errors import EndpointError, RateLimitError

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
        self._pool: EndpointPool | None = None
        self._default_tag: str = "default"

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
    async def chat(self, messages: list, tool_choice: str | None = None,
                   tag: str | None = None) -> ChatResponse:
        """Send messages to AI with automatic endpoint rotation.

        tag: which endpoint group to use. Defaults to self._default_tag.
        tool_choice: optional hint ("auto", "required", "none").
        Appends assistant response to messages. Returns parsed response.
        """


class OpenAIProvider(BaseProvider):
    """Provider format for OpenAI-compatible APIs with rotation support.

    When an EndpointPool is injected, chat() automatically rotates through
    available endpoints on failure. Without a pool, subclasses (like mock)
    override chat() directly.
    """

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

    async def chat(self, messages: list, tool_choice: str | None = None,
                   tag: str | None = None) -> ChatResponse:
        """Send messages with automatic endpoint rotation on failure."""
        if not self._pool:
            # No pool — subclass should override (e.g., mock provider)
            return ChatResponse(text="[AI Error] No endpoint pool configured")

        effective_tag = tag or self._default_tag
        endpoints = self._pool.get_available(effective_tag)
        if not endpoints:
            logger.error("No available endpoints for tag '%s'", effective_tag)
            return ChatResponse(text=f"[AI Error] No available endpoints for tag '{effective_tag}'")

        last_error: Exception | None = None
        for i, endpoint in enumerate(endpoints):
            try:
                if i > 0:
                    logger.info("Rotating to endpoint '%s' (attempt %d/%d)",
                                endpoint.name, i + 1, len(endpoints))
                return await self._http_chat(endpoint, messages, tool_choice)
            except RateLimitError as e:
                logger.warning(
                    "Endpoint '%s' rate limited (cooldown %.0fs), trying next",
                    endpoint.name, e.retry_after,
                )
                self._pool.mark_cooldown(endpoint.name, e.retry_after)
                last_error = e
            except EndpointError as e:
                logger.warning(
                    "Endpoint '%s' error (HTTP %d), trying next",
                    endpoint.name, e.status,
                )
                last_error = e
            except Exception as e:
                logger.warning(
                    "Endpoint '%s' unexpected error: %s, trying next",
                    endpoint.name, e,
                )
                last_error = e

        # All endpoints failed — advance cursor so next request starts from a different one
        self._pool.advance_cursor(effective_tag)
        logger.error("All endpoints failed for tag '%s': %s", effective_tag, last_error)
        return ChatResponse(text=f"[AI Error] All endpoints failed: {last_error}")

    async def _http_chat(self, endpoint: EndpointConfig, messages: list,
                         tool_choice: str | None) -> ChatResponse:
        """Execute a single HTTP chat request to one OpenAI-compatible endpoint.

        Raises RateLimitError on 429, EndpointError on other non-200 status.
        On success, appends assistant message to messages list and returns parsed response.
        """
        import aiohttp

        headers = {"Content-Type": "application/json"}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"

        payload: dict = {"model": endpoint.model, "messages": messages}
        if self.tools:
            payload["tools"] = self.tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        url = f"{endpoint.base_url}/chat/completions"
        logger.info("Chat request -> %s (model=%s, messages=%d)",
                    endpoint.name, endpoint.model, len(messages))

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 429:
                    retry_after = float(resp.headers.get("Retry-After", "60"))
                    raise RateLimitError(retry_after=retry_after)
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Endpoint '%s' HTTP %d: %s", endpoint.name, resp.status, text[:200])
                    raise EndpointError(resp.status, text[:200])
                data = await resp.json()

        msg = data["choices"][0]["message"]
        messages.append(msg)

        tool_calls = self.parse_tool_calls(msg)
        if tool_calls:
            logger.debug("AI requested %d tool call(s) via '%s'", len(tool_calls), endpoint.name)
            return ChatResponse(tool_calls=tool_calls)

        text = msg.get("content") or "..."
        logger.debug("Chat response from '%s' (length=%d)", endpoint.name, len(text))
        return ChatResponse(text=text)


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

    async def chat(self, messages: list, tool_choice: str | None = None,
                   tag: str | None = None) -> ChatResponse:
        """Anthropic chat with rotation — same pattern as OpenAIProvider.

        Deferred: _http_chat for Anthropic format is not yet implemented.
        Will be added when an Anthropic endpoint is configured.
        """
        return ChatResponse(text="[AI Error] Anthropic provider chat not yet implemented")
