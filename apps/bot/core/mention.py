"""Mention handling — tool-call loop, memory load/save, and summarization.

The tool-call loop lets the AI call tools multiple times in sequence.
Each round: AI responds → core executes any tool calls → results fed back.
The loop ends when the AI returns a text response (no tool calls), or after
MAX_TOOL_ROUNDS. A 1-second pause between rounds prevents API rate limiting.

Memory integration: before the loop, load conversation history and summary
from the database. After the loop, save the new turn and optionally trigger
summarization of old turns.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

import jsonschema

from apps.bot.config.prompts import build_system_prompt
from apps.bot.core.loader import format_tool_hints
from apps.bot.memory.database import Database
from apps.bot.provider.base import BaseProvider

logger = logging.getLogger("synapulse.core")

MAX_TOOL_ROUNDS = 10
# Truncate tool results in logs to keep them readable.
_LOG_RESULT_MAX = 200
# Compress consumed tool results longer than this to save tokens on subsequent rounds.
_COMPRESS_THRESHOLD = 200
# Max characters of conversation history injected into user prompt.
_HISTORY_CONTEXT_CAP = 3000
# Max characters of task summary injected into system prompt.
_TASK_CONTEXT_CAP = 1000
# Summarize when turn count exceeds this threshold.
_SUMMARIZE_THRESHOLD = 20
# Keep the most recent N turns when summarizing (don't summarize these).
_SUMMARIZE_KEEP_RECENT = 5

_SUMMARIZE_PROMPT = (
    "Summarize the following conversation between a user and an AI assistant. "
    "Include: key topics discussed, user preferences or facts discovered, "
    "important conclusions or decisions. Be concise (under 500 words). "
    "Write in the same language the user used."
)

# Type for the raw channel send_file callback: (channel_id, file_path, comment) -> None
_ChannelSendFile = Callable[[str, str, str], Coroutine[Any, Any, None]]


def make_mention_handler(
        provider: BaseProvider,
        tools: dict,
        send_file: _ChannelSendFile | None = None,
        db: Database | None = None,
) -> Callable[[str, str, str, list[dict[str, str]] | None, str | None], Coroutine[Any, Any, str]]:
    """Create a handle_mention callback with provider, tools, and db closed over."""

    # Build tool hints once (static part of prompt).
    tool_hints = format_tool_hints(tools) if tools else ""

    async def handle_mention(
            content: str,
            channel_id: str = "",
            user_id: str = "default",
            history: list[dict[str, str]] | None = None,
            referenced_content: str | None = None,
    ) -> str:
        """Process an @mention: load memory, call AI, save turn, maybe summarize.

        This function ALWAYS returns a string — errors are caught and turned into
        user-visible messages so the channel never gets an unhandled exception.
        """
        try:
            return await _handle_mention_inner(content, channel_id, user_id, history, referenced_content)
        except Exception:
            logger.exception("Unhandled error in mention handler")
            return "Something went wrong while processing your request. Please try again later."

    async def _handle_mention_inner(
            content: str,
            channel_id: str = "",
            user_id: str = "default",
            history: list[dict[str, str]] | None = None,
            referenced_content: str | None = None,
    ) -> str:
        # Inject scoped callbacks into tools for this message
        if send_file and channel_id:
            scoped = partial(send_file, channel_id)
            for tool in tools.values():
                tool.send_file = scoped

        # Inject channel_id into reminder tool for this message
        for tool in tools.values():
            if hasattr(tool, "channel_id"):
                tool.channel_id = channel_id

        logger.info("Handling mention (length=%d, user=%s, channel=%s, history=%d)",
                    len(content), user_id, channel_id, len(history or []))
        logger.info("Available tools: %s", list(tools.keys()) if tools else "(none)")

        # --- Load memory and task context from database ---
        memory_summary = None
        task_summary = None
        stored_turns = []
        if db:
            try:
                memory_summary = await db.load_summary(user_id, channel_id)
                stored_turns = await db.load_turns(user_id, channel_id, limit=20)
                logger.info("Loaded memory: summary=%s, turns=%d",
                            "yes" if memory_summary else "no", len(stored_turns))
            except Exception:
                logger.exception("Failed to load memory, proceeding without")

            try:
                pending_tasks = await db.get_pending_tasks_summary(user_id)
                if pending_tasks:
                    task_summary = _format_task_summary(pending_tasks)
                    logger.info("Loaded %d pending tasks for context", len(pending_tasks))
            except Exception:
                logger.exception("Failed to load tasks, proceeding without")

        # --- Build system prompt with memory and tasks ---
        system_prompt = build_system_prompt(tool_hints, memory_summary, task_summary)

        # --- Build user prompt from content + stored history + channel history + reference ---
        user_prompt = _build_user_prompt(content, stored_turns, history, referenced_content)

        messages = provider.build_messages(system_prompt, user_prompt)

        # --- Tool-call loop: core orchestrates, provider formats messages ---
        tool_names_used = []
        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            logger.info("--- Tool-call loop round %d/%d ---", round_num, MAX_TOOL_ROUNDS)
            response = await provider.chat(messages)

            if not response.tool_calls:
                text = response.text or "..."
                preview = text[:_LOG_RESULT_MAX].replace("\n", " | ")
                logger.info("AI returned text (round %d, length=%d): %s",
                            round_num, len(text), preview)

                # --- Save turn to database ---
                if db:
                    await _save_turn(db, user_id, channel_id, content, text, tool_names_used)
                    await _maybe_summarize(db, provider, user_id, channel_id)

                return text

            logger.info("AI requested %d tool call(s) in round %d: %s",
                        len(response.tool_calls), round_num,
                        [c.name for c in response.tool_calls])

            # AI has consumed all current messages — compress old tool results
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

                tool_names_used.append(call.name)
                # Collapse newlines so multi-line results stay on one log line.
                preview = result[:_LOG_RESULT_MAX].replace("\n", " | ")
                logger.info("Tool result from %s (length=%d): %s",
                            call.name, len(result), preview)
                provider.append_tool_result(messages, call, result)

            # Pause between rounds to avoid hitting provider API rate limits.
            logger.debug("Sleeping 1s before next round")
            await asyncio.sleep(1)

        logger.warning("Tool-call loop hit max rounds (%d)", MAX_TOOL_ROUNDS)
        max_round_reply = "Sorry, I got stuck in a loop. Please try again."

        if db:
            await _save_turn(db, user_id, channel_id, content, max_round_reply, tool_names_used)

        return max_round_reply

    return handle_mention


def _build_user_prompt(
        content: str,
        stored_turns: list[dict],
        channel_history: list[dict[str, str]] | None,
        referenced_content: str | None = None,
) -> str:
    """Build user prompt with conversation context from stored turns, channel history, and reference."""
    parts = []

    # Stored conversation history from database (cross-session memory)
    if stored_turns:
        turn_lines = []
        total_chars = 0
        for turn in stored_turns:
            line = f"{turn['role']}: {turn['content']}"
            if total_chars + len(line) > _HISTORY_CONTEXT_CAP:
                break
            turn_lines.append(line)
            total_chars += len(line)
        if turn_lines:
            parts.append("[Previous conversation history]\n" + "\n".join(turn_lines))

    # Recent channel messages (Discord real-time context)
    if channel_history:
        context = "\n".join(f"{m['author']}: {m['content']}" for m in channel_history)
        parts.append(f"[Recent channel messages]\n{context}")

    # Referenced bot message (user replied to a bot message)
    if referenced_content:
        parts.append(f"[Referenced bot message]\n{referenced_content}")

    # Current user message
    parts.append(f"[User message]\n{content}")

    return "\n\n".join(parts)


def _format_task_summary(tasks: list[dict]) -> str:
    """Format pending tasks into a compact summary for system prompt injection."""
    lines = []
    total_chars = 0
    for t in tasks:
        due = f" (due {t['due_date']})" if t.get("due_date") else ""
        prio = f" [{t['priority']}]" if t["priority"] != "medium" else ""
        line = f"#{t['id']}{prio}{due}: {t['title']}"
        if total_chars + len(line) > _TASK_CONTEXT_CAP:
            lines.append(f"... and {len(tasks) - len(lines)} more")
            break
        lines.append(line)
        total_chars += len(line)
    return "\n".join(lines)


async def _save_turn(
        db: Database, user_id: str, channel_id: str,
        user_content: str, ai_reply: str, tool_names: list[str],
) -> None:
    """Save user message and AI reply to database."""
    try:
        tool_summary = ", ".join(dict.fromkeys(tool_names)) if tool_names else ""
        await db.save_turn(user_id, channel_id, "user", user_content, "")
        await db.save_turn(user_id, channel_id, "assistant", ai_reply, tool_summary)
    except Exception:
        logger.exception("Failed to save conversation turn")


async def _maybe_summarize(
        db: Database, provider: BaseProvider, user_id: str, channel_id: str,
) -> None:
    """Summarize old conversation turns if count exceeds threshold."""
    try:
        count = await db.count_turns(user_id, channel_id)
        if count <= _SUMMARIZE_THRESHOLD:
            return

        logger.info("Turn count %d exceeds threshold %d, summarizing", count, _SUMMARIZE_THRESHOLD)
        all_turns = await db.load_turns(user_id, channel_id, limit=count)

        # Keep recent turns, summarize the rest
        old_turns = all_turns[:-_SUMMARIZE_KEEP_RECENT]
        if not old_turns:
            return

        # Build text for summarization
        old_text = "\n".join(f"{t['role']}: {t['content']}" for t in old_turns)

        # Include existing summary for cascading summarization
        existing = await db.load_summary(user_id, channel_id)
        if existing:
            old_text = f"[Previous summary]\n{existing}\n\n[New conversations]\n{old_text}"

        messages = provider.build_messages(_SUMMARIZE_PROMPT, old_text)
        response = await provider.chat(messages)
        summary = response.text

        if not summary:
            logger.warning("Summarization returned empty, skipping")
            return

        await db.save_summary(user_id, channel_id, summary)

        # Delete only the summarized turns (keep recent ones)
        cutoff = old_turns[-1]["created_at"]
        await db.clear_turns(user_id, channel_id, before=cutoff)
        logger.info("Summarized %d turns, kept %d recent", len(old_turns), _SUMMARIZE_KEEP_RECENT)

    except Exception:
        logger.exception("Summarization failed, keeping raw turns")
