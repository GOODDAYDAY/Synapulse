"""Mention handling — tool-call loop and message building."""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from apps.bot.config.prompts import SYSTEM_PROMPT
from apps.bot.provider.base import BaseProvider

logger = logging.getLogger("synapulse.core")

MAX_TOOL_ROUNDS = 10


def make_mention_handler(
        provider: BaseProvider,
        tools: dict,
) -> Callable[[str, list[dict[str, str]] | None], Coroutine[Any, Any, str]]:
    """Create a handle_mention callback with provider and tools closed over."""

    async def handle_mention(
            content: str,
            history: list[dict[str, str]] | None = None,
    ) -> str:
        """Process an @mention: build context, call provider, orchestrate tool-call loop."""
        logger.info("Handling mention (length=%d, history=%d)", len(content), len(history or []))

        # Build user prompt from content + history
        if history:
            context = "\n".join(f"{m['author']}: {m['content']}" for m in history)
            user_prompt = f"[Recent channel messages]\n{context}\n\n[User message]\n{content}"
        else:
            user_prompt = content

        messages = provider.build_messages(SYSTEM_PROMPT, user_prompt)

        # Tool-call loop: core orchestrates, provider formats messages
        for _ in range(MAX_TOOL_ROUNDS):
            response = await provider.chat(messages)

            if not response.tool_calls:
                logger.debug("Reply generated (length=%d)", len(response.text or ""))
                return response.text or "..."

            for call in response.tool_calls:
                tool = tools.get(call.name)
                if not tool:
                    logger.warning("Unknown tool requested: %s", call.name)
                    provider.append_tool_result(messages, call, f"Error: unknown tool '{call.name}'")
                    continue

                logger.info("Executing tool: %s(%s)", call.name, call.arguments)
                try:
                    result = await tool.execute(**call.arguments)
                except Exception as e:
                    logger.exception("Tool execution failed: %s", call.name)
                    result = f"Error: {e}"
                provider.append_tool_result(messages, call, result)

        logger.warning("Tool-call loop hit max rounds (%d)", MAX_TOOL_ROUNDS)
        return "Sorry, I got stuck in a loop. Please try again."

    return handle_mention
