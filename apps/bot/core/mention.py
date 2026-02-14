"""Mention handling — tool-call loop and message building.

The tool-call loop lets the AI call tools multiple times in sequence.
Each round: AI responds → core executes any tool calls → results fed back.
The loop ends when the AI returns a text response (no tool calls), or after
MAX_TOOL_ROUNDS. A 1-second pause between rounds prevents API rate limiting.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import jsonschema

from apps.bot.config.prompts import SYSTEM_PROMPT, TOOLS_GUIDANCE
from apps.bot.core.loader import format_tool_hints
from apps.bot.provider.base import BaseProvider

logger = logging.getLogger("synapulse.core")

MAX_TOOL_ROUNDS = 10
# Truncate tool results in logs to keep them readable.
_LOG_RESULT_MAX = 200
# Compress consumed tool results longer than this to save tokens on subsequent rounds.
_COMPRESS_THRESHOLD = 200


def make_mention_handler(
        provider: BaseProvider,
        tools: dict,
) -> Callable[[str, list[dict[str, str]] | None], Coroutine[Any, Any, str]]:
    """Create a handle_mention callback with provider and tools closed over."""

    # Build system prompt once — base identity + dynamic tool hints (if any).
    if tools:
        hints = format_tool_hints(tools)
        system_prompt = f"{SYSTEM_PROMPT}\n## Tools\n{TOOLS_GUIDANCE}{hints}\n"
    else:
        system_prompt = SYSTEM_PROMPT

    async def handle_mention(
            content: str,
            history: list[dict[str, str]] | None = None,
    ) -> str:
        """Process an @mention: build context, call provider, orchestrate tool-call loop.

        This function ALWAYS returns a string — errors are caught and turned into
        user-visible messages so the channel never gets an unhandled exception.
        """
        try:
            return await _handle_mention_inner(content, history)
        except Exception:
            logger.exception("Unhandled error in mention handler")
            return "Something went wrong while processing your request. Please try again later."

    async def _handle_mention_inner(
            content: str,
            history: list[dict[str, str]] | None = None,
    ) -> str:
        logger.info("Handling mention (length=%d, history=%d)", len(content), len(history or []))
        logger.info("Available tools: %s", list(tools.keys()) if tools else "(none)")

        # Build user prompt from content + history
        if history:
            context = "\n".join(f"{m['author']}: {m['content']}" for m in history)
            user_prompt = f"[Recent channel messages]\n{context}\n\n[User message]\n{content}"
        else:
            user_prompt = content

        messages = provider.build_messages(system_prompt, user_prompt)

        # Tool-call loop: core orchestrates, provider formats messages
        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            logger.info("--- Tool-call loop round %d/%d ---", round_num, MAX_TOOL_ROUNDS)
            response = await provider.chat(messages)

            if not response.tool_calls:
                text = response.text or "..."
                preview = text[:_LOG_RESULT_MAX].replace("\n", " | ")
                logger.info("AI returned text (round %d, length=%d): %s",
                            round_num, len(text), preview)
                return text

            logger.info("AI requested %d tool call(s) in round %d: %s",
                        len(response.tool_calls), round_num,
                        [c.name for c in response.tool_calls])

            # AI has consumed all current messages — compress old tool results
            # so the next round doesn't re-send large payloads.
            provider.compress_tool_results(messages, _COMPRESS_THRESHOLD)

            for call in response.tool_calls:
                tool = tools.get(call.name)
                if not tool:
                    logger.warning("Unknown tool requested: %s", call.name)
                    provider.append_tool_result(messages, call, f"Error: unknown tool '{call.name}'")
                    continue

                # Validate arguments against tool's JSON Schema before executing.
                try:
                    jsonschema.validate(call.arguments, tool.parameters)
                except jsonschema.ValidationError as e:
                    logger.warning("Invalid arguments for %s: %s", call.name, e.message)
                    provider.append_tool_result(
                        messages, call,
                        f"Parameter error: {e.message}. Check the tool schema and retry.",
                    )
                    continue

                logger.info("Executing tool: %s(%s)", call.name, call.arguments)
                try:
                    result = await tool.execute(**call.arguments)
                except Exception as e:
                    logger.exception("Tool execution failed: %s", call.name)
                    result = f"Error: {e}"

                # Collapse newlines so multi-line results stay on one log line.
                preview = result[:_LOG_RESULT_MAX].replace("\n", " | ")
                logger.info("Tool result from %s (length=%d): %s",
                            call.name, len(result), preview)
                provider.append_tool_result(messages, call, result)

            # Pause between rounds to avoid hitting provider API rate limits.
            # Tools like local_files may need many rounds (browse → drill down → read),
            # each round triggers a provider.chat() call on the next iteration.
            logger.debug("Sleeping 1s before next round")
            await asyncio.sleep(1)

        logger.warning("Tool-call loop hit max rounds (%d)", MAX_TOOL_ROUNDS)
        return "Sorry, I got stuck in a loop. Please try again."

    return handle_mention
