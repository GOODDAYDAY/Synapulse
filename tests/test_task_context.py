"""Tests for task context injection — covers REQ-003 AC-06, AC-07."""

from apps.bot.config.prompts import build_system_prompt
from apps.bot.core.mention import _build_user_prompt, _format_task_summary


def test_build_prompt_with_task_summary():
    """AC-06: Task summary appears in system prompt."""
    prompt = build_system_prompt("- task: manage tasks", task_summary="#1 [high]: Submit report")
    assert "Pending Tasks" in prompt
    assert "Submit report" in prompt


def test_build_prompt_without_tasks():
    """AC-07: No task section when no pending tasks."""
    prompt = build_system_prompt("- task: manage tasks", task_summary=None)
    assert "Pending Tasks" not in prompt


def test_build_prompt_with_both_memory_and_tasks():
    prompt = build_system_prompt(
        "- task: manage tasks",
        memory_summary="User likes Python",
        task_summary="#1: Fix bug",
    )
    assert "Memory" in prompt
    assert "Pending Tasks" in prompt
    assert "Tools" in prompt


def test_task_summary_capped():
    """Task summary respects cap."""
    long_summary = "x" * 5000
    prompt = build_system_prompt("hints", task_summary=long_summary)
    # Summary is capped at 1000 chars
    assert len(prompt) < len(long_summary)


def test_format_task_summary_basic():
    tasks = [
        {"id": 1, "title": "Submit report", "priority": "high", "due_date": "2026-03-14"},
        {"id": 2, "title": "Buy groceries", "priority": "medium", "due_date": None},
    ]
    result = _format_task_summary(tasks)
    assert "#1 [high] (due 2026-03-14): Submit report" in result
    assert "#2: Buy groceries" in result  # medium priority omitted


def test_format_task_summary_empty():
    result = _format_task_summary([])
    assert result == ""


def test_user_prompt_with_referenced_content():
    """AC-08/09: Referenced bot message appears in user prompt."""
    prompt = _build_user_prompt(
        content="translate to Chinese",
        stored_turns=[],
        channel_history=None,
        referenced_content="New email from John: Meeting tomorrow at 3pm",
    )
    assert "[Referenced bot message]" in prompt
    assert "New email from John" in prompt
    assert "translate to Chinese" in prompt


def test_user_prompt_without_referenced_content():
    prompt = _build_user_prompt(
        content="hello",
        stored_turns=[],
        channel_history=None,
        referenced_content=None,
    )
    assert "[Referenced bot message]" not in prompt
    assert "hello" in prompt
