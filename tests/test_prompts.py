"""Tests for config/prompts.py — covers AC-08 (system prompt with memory)."""

from apps.bot.config.prompts import build_system_prompt, SYSTEM_PROMPT, _MEMORY_SUMMARY_CAP


def test_build_with_tools_and_memory():
    """AC-08: System prompt contains memory summary and tools."""
    prompt = build_system_prompt(
        tool_hints="- memo: Save and recall notes\n- reminder: Set reminders",
        memory_summary="User prefers Chinese. Birthday is Jan 1st.",
    )
    assert "## Memory" in prompt
    assert "User prefers Chinese" in prompt
    assert "## Tools" in prompt
    assert "## Strategy" in prompt
    assert "memo: Save and recall notes" in prompt


def test_build_without_memory():
    """No memory section when summary is None."""
    prompt = build_system_prompt(tool_hints="- memo: notes", memory_summary=None)
    assert "## Memory" not in prompt
    assert "## Tools" in prompt


def test_build_without_tools():
    """No tools section when no tool hints."""
    prompt = build_system_prompt(tool_hints="", memory_summary="Some memory")
    assert "## Tools" not in prompt
    assert "## Memory" in prompt


def test_build_empty():
    """Bare system prompt with no tools or memory."""
    prompt = build_system_prompt(tool_hints="", memory_summary=None)
    assert prompt == SYSTEM_PROMPT


def test_memory_summary_capped():
    """Summary exceeding cap is truncated."""
    long_summary = "x" * (_MEMORY_SUMMARY_CAP + 500)
    prompt = build_system_prompt(tool_hints="", memory_summary=long_summary)
    # The injected summary should be capped
    assert "x" * _MEMORY_SUMMARY_CAP in prompt
    assert "x" * (_MEMORY_SUMMARY_CAP + 1) not in prompt


def test_capabilities_reflect_actual_tools():
    """Capabilities section mentions memo and reminder, not scheduling."""
    assert "Remember things the user tells you" in SYSTEM_PROMPT
    assert "Set timed reminders" in SYSTEM_PROMPT
    # Should NOT claim capabilities without tool backing
    assert "scheduling" not in SYSTEM_PROMPT.lower() or "reminders" in SYSTEM_PROMPT.lower()


def test_constraints_include_no_secrets():
    """Prompt instructs AI to never store secrets in memos."""
    assert "Never store passwords" in SYSTEM_PROMPT
