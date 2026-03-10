"""Tests for memo and reminder tools — covers AC-04, AC-05, AC-06, AC-09."""

import os
import tempfile

import pytest
import pytest_asyncio

from apps.bot.memory.database import Database
from apps.bot.tool.memo.handler import Tool as MemoTool
from apps.bot.tool.reminder.handler import Tool as ReminderTool


@pytest_asyncio.fixture
async def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        database = Database()
        await database.init(db_path)
        yield database
        await database.close()


@pytest_asyncio.fixture
async def memo_tool(db):
    tool = MemoTool()
    tool.db = db
    tool.channel_id = "test_channel"
    return tool


@pytest_asyncio.fixture
async def reminder_tool(db):
    tool = ReminderTool()
    tool.db = db
    tool.channel_id = "test_channel"
    return tool


# --- Memo Tool (F-03, AC-04, AC-05) ---

@pytest.mark.asyncio
async def test_memo_save(memo_tool):
    """AC-04: Save a memo."""
    result = await memo_tool.execute(action="save", content="My birthday is January 1st")
    assert "Saved memo #" in result


@pytest.mark.asyncio
async def test_memo_search(memo_tool):
    """AC-04: Search for a saved memo."""
    await memo_tool.execute(action="save", content="My birthday is January 1st")
    result = await memo_tool.execute(action="search", content="birthday")
    assert "January 1st" in result


@pytest.mark.asyncio
async def test_memo_list(memo_tool):
    await memo_tool.execute(action="save", content="Note 1")
    await memo_tool.execute(action="save", content="Note 2")
    result = await memo_tool.execute(action="list")
    assert "Note 1" in result
    assert "Note 2" in result


@pytest.mark.asyncio
async def test_memo_delete(memo_tool):
    result = await memo_tool.execute(action="save", content="To delete")
    # Extract memo ID from "Saved memo #N."
    memo_id = int(result.split("#")[1].rstrip("."))
    result = await memo_tool.execute(action="delete", memo_id=memo_id)
    assert "Deleted" in result


@pytest.mark.asyncio
async def test_memo_delete_nonexistent(memo_tool):
    result = await memo_tool.execute(action="delete", memo_id=9999)
    assert "not found" in result


@pytest.mark.asyncio
async def test_memo_save_empty(memo_tool):
    result = await memo_tool.execute(action="save", content="")
    assert "Error" in result


@pytest.mark.asyncio
async def test_memo_duplicate_detection(memo_tool):
    """F-03 edge case: warn on duplicate."""
    await memo_tool.execute(action="save", content="Server IP is 10.0.0.1")
    result = await memo_tool.execute(action="save", content="Server IP is 10.0.0.1")
    assert "similar memo already exists" in result


@pytest.mark.asyncio
async def test_memo_search_no_match(memo_tool):
    await memo_tool.execute(action="save", content="Hello world")
    result = await memo_tool.execute(action="search", content="nonexistent")
    assert "No memos matching" in result


@pytest.mark.asyncio
async def test_memo_clear_history(memo_tool, db):
    """AC-09: Clear conversation history via tool."""
    # Save some conversation turns
    await db.save_turn("default", "test_channel", "user", "Hello")
    await db.save_turn("default", "test_channel", "assistant", "Hi!")
    await db.save_summary("default", "test_channel", "Some summary")
    # Save a memo (should NOT be cleared)
    await memo_tool.execute(action="save", content="Keep this memo")

    result = await memo_tool.execute(action="clear_history")
    assert "Cleared" in result
    assert "Memos are preserved" in result

    # Verify turns and summary are gone
    assert await db.count_turns("default", "test_channel") == 0
    assert await db.load_summary("default", "test_channel") is None
    # Verify memo is preserved
    memos = await db.list_memos("default")
    assert len(memos) == 1
    assert memos[0]["content"] == "Keep this memo"


# --- Reminder Tool (F-04, AC-06) ---

@pytest.mark.asyncio
async def test_reminder_create(reminder_tool):
    """AC-06: Create a reminder."""
    result = await reminder_tool.execute(
        action="create", remind_at="2099-01-01T15:00:00", message="Drink water",
    )
    assert "Reminder #" in result
    assert "2099-01-01 15:00" in result


@pytest.mark.asyncio
async def test_reminder_list(reminder_tool):
    await reminder_tool.execute(
        action="create", remind_at="2099-01-01T15:00:00", message="Task A",
    )
    result = await reminder_tool.execute(action="list")
    assert "Task A" in result


@pytest.mark.asyncio
async def test_reminder_cancel(reminder_tool):
    result = await reminder_tool.execute(
        action="create", remind_at="2099-01-01T15:00:00", message="Cancel me",
    )
    rid = int(result.split("#")[1].split(" ")[0])
    result = await reminder_tool.execute(action="cancel", reminder_id=rid)
    assert "Cancelled" in result


@pytest.mark.asyncio
async def test_reminder_cancel_nonexistent(reminder_tool):
    result = await reminder_tool.execute(action="cancel", reminder_id=9999)
    assert "not found" in result


@pytest.mark.asyncio
async def test_reminder_invalid_time(reminder_tool):
    result = await reminder_tool.execute(
        action="create", remind_at="not-a-date", message="Test",
    )
    assert "Error" in result
    assert "ISO 8601" in result


@pytest.mark.asyncio
async def test_reminder_missing_message(reminder_tool):
    result = await reminder_tool.execute(
        action="create", remind_at="2099-01-01T15:00:00", message="",
    )
    assert "Error" in result


@pytest.mark.asyncio
async def test_reminder_recurring(reminder_tool):
    result = await reminder_tool.execute(
        action="create", remind_at="2099-01-01T15:00:00",
        message="Daily check", recurrence="daily",
    )
    assert "repeats daily" in result
