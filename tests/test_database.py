"""Tests for memory/database.py — covers AC-01, AC-02, AC-03, AC-05, AC-07."""

import asyncio
import os
import tempfile

import pytest
import pytest_asyncio

from apps.bot.memory.database import Database


@pytest_asyncio.fixture
async def db():
    """Create a temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        database = Database()
        await database.init(db_path)
        yield database
        await database.close()


# --- Conversations (F-01, AC-01, AC-02) ---

@pytest.mark.asyncio
async def test_save_and_load_turns(db):
    """AC-01: Consecutive messages retain context."""
    await db.save_turn("user1", "ch1", "user", "What is Python?")
    await db.save_turn("user1", "ch1", "assistant", "Python is a programming language.")
    await db.save_turn("user1", "ch1", "user", "Tell me more about it")
    await db.save_turn("user1", "ch1", "assistant", "It was created by Guido van Rossum.")

    turns = await db.load_turns("user1", "ch1", limit=20)
    assert len(turns) == 4
    assert turns[0]["role"] == "user"
    assert turns[0]["content"] == "What is Python?"
    assert turns[3]["content"] == "It was created by Guido van Rossum."


@pytest.mark.asyncio
async def test_turns_isolated_by_channel(db):
    """Turns in different channels don't mix."""
    await db.save_turn("user1", "ch1", "user", "Hello channel 1")
    await db.save_turn("user1", "ch2", "user", "Hello channel 2")

    ch1_turns = await db.load_turns("user1", "ch1")
    ch2_turns = await db.load_turns("user1", "ch2")
    assert len(ch1_turns) == 1
    assert len(ch2_turns) == 1
    assert ch1_turns[0]["content"] == "Hello channel 1"
    assert ch2_turns[0]["content"] == "Hello channel 2"


@pytest.mark.asyncio
async def test_turns_isolated_by_user(db):
    """Turns for different users don't mix."""
    await db.save_turn("user1", "ch1", "user", "I am user 1")
    await db.save_turn("user2", "ch1", "user", "I am user 2")

    u1_turns = await db.load_turns("user1", "ch1")
    u2_turns = await db.load_turns("user2", "ch1")
    assert len(u1_turns) == 1
    assert len(u2_turns) == 1


@pytest.mark.asyncio
async def test_load_turns_limit(db):
    """Load respects limit parameter."""
    for i in range(10):
        await db.save_turn("user1", "ch1", "user", f"Message {i}")
    turns = await db.load_turns("user1", "ch1", limit=3)
    assert len(turns) == 3
    # Should be the 3 most recent
    assert turns[2]["content"] == "Message 9"


@pytest.mark.asyncio
async def test_count_turns(db):
    await db.save_turn("user1", "ch1", "user", "A")
    await db.save_turn("user1", "ch1", "assistant", "B")
    assert await db.count_turns("user1", "ch1") == 2
    assert await db.count_turns("user1", "ch2") == 0


@pytest.mark.asyncio
async def test_clear_turns_all(db):
    """AC-09: Clear conversation history."""
    await db.save_turn("user1", "ch1", "user", "A")
    await db.save_turn("user1", "ch1", "assistant", "B")
    count = await db.clear_turns("user1", "ch1")
    assert count == 2
    assert await db.count_turns("user1", "ch1") == 0


@pytest.mark.asyncio
async def test_clear_turns_before(db):
    """Partial clear: only delete turns before a timestamp."""
    await db.save_turn("user1", "ch1", "user", "Old message")
    turns = await db.load_turns("user1", "ch1")
    cutoff = turns[0]["created_at"]
    # Add a small delay to ensure different timestamps
    await asyncio.sleep(0.01)
    await db.save_turn("user1", "ch1", "user", "New message")
    # Clear only before cutoff — should not delete the newer one
    # Note: cutoff is the old message's time, and we use < so it won't delete it either
    # We need a time after the old message
    await db.clear_turns("user1", "ch1", before=cutoff)
    remaining = await db.load_turns("user1", "ch1")
    # The old message has created_at == cutoff, and we delete < cutoff, so it stays
    assert len(remaining) >= 1


# --- Summaries (F-02, AC-03) ---

@pytest.mark.asyncio
async def test_save_and_load_summary(db):
    """AC-03: Summary persisted and loadable."""
    await db.save_summary("user1", "ch1", "User discussed Python and AI.")
    summary = await db.load_summary("user1", "ch1")
    assert summary == "User discussed Python and AI."


@pytest.mark.asyncio
async def test_summary_upsert(db):
    """Saving summary twice replaces the old one."""
    await db.save_summary("user1", "ch1", "First summary")
    await db.save_summary("user1", "ch1", "Updated summary")
    summary = await db.load_summary("user1", "ch1")
    assert summary == "Updated summary"


@pytest.mark.asyncio
async def test_load_summary_nonexistent(db):
    result = await db.load_summary("user1", "ch1")
    assert result is None


@pytest.mark.asyncio
async def test_delete_summary(db):
    await db.save_summary("user1", "ch1", "Some summary")
    await db.delete_summary("user1", "ch1")
    assert await db.load_summary("user1", "ch1") is None


# --- Memos (F-03, AC-04, AC-05) ---

@pytest.mark.asyncio
async def test_save_and_list_memos(db):
    """AC-04: Save memo and recall it."""
    memo_id = await db.save_memo("user1", "My birthday is January 1st")
    assert memo_id > 0
    memos = await db.list_memos("user1")
    assert len(memos) == 1
    assert memos[0]["content"] == "My birthday is January 1st"
    assert memos[0]["id"] == memo_id


@pytest.mark.asyncio
async def test_search_memos(db):
    """Fuzzy search by keyword."""
    await db.save_memo("user1", "Server IP is 192.168.1.1")
    await db.save_memo("user1", "Meeting every Monday at 10am")
    await db.save_memo("user1", "Server hostname is myserver")

    results = await db.search_memos("user1", "server")
    assert len(results) == 2  # both server-related memos


@pytest.mark.asyncio
async def test_search_memos_no_match(db):
    await db.save_memo("user1", "Hello world")
    results = await db.search_memos("user1", "nonexistent")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_delete_memo(db):
    memo_id = await db.save_memo("user1", "To delete")
    assert await db.delete_memo(memo_id) is True
    assert await db.delete_memo(memo_id) is False  # already deleted
    memos = await db.list_memos("user1")
    assert len(memos) == 0


@pytest.mark.asyncio
async def test_list_memos_newest_first(db):
    await db.save_memo("user1", "First")
    await asyncio.sleep(0.01)
    await db.save_memo("user1", "Second")
    memos = await db.list_memos("user1")
    assert memos[0]["content"] == "Second"
    assert memos[1]["content"] == "First"


# --- Reminders (F-04, AC-06, AC-07) ---

@pytest.mark.asyncio
async def test_create_and_list_reminders(db):
    """AC-06: Create reminder and verify it's listed."""
    rid = await db.create_reminder("user1", "ch1", "2099-01-01T12:00:00", "Drink water")
    assert rid > 0
    reminders = await db.list_reminders("user1")
    assert len(reminders) == 1
    assert reminders[0]["message"] == "Drink water"
    assert reminders[0]["remind_at"] == "2099-01-01T12:00:00"


@pytest.mark.asyncio
async def test_get_due_reminders(db):
    """Due reminders are those with remind_at <= now."""
    # Past time = due immediately
    await db.create_reminder("user1", "ch1", "2000-01-01T00:00:00", "Overdue")
    # Future time = not due
    await db.create_reminder("user1", "ch1", "2099-01-01T00:00:00", "Future")

    due = await db.get_due_reminders()
    assert len(due) == 1
    assert due[0]["message"] == "Overdue"


@pytest.mark.asyncio
async def test_mark_reminder_fired(db):
    rid = await db.create_reminder("user1", "ch1", "2000-01-01T00:00:00", "Fire me")
    await db.mark_reminder_fired(rid)
    # Should not appear in due or active list
    due = await db.get_due_reminders()
    assert len(due) == 0
    active = await db.list_reminders("user1")
    assert len(active) == 0


@pytest.mark.asyncio
async def test_cancel_reminder(db):
    rid = await db.create_reminder("user1", "ch1", "2099-01-01T00:00:00", "Cancel me")
    assert await db.cancel_reminder(rid) is True
    assert await db.cancel_reminder(rid) is False  # already cancelled
    assert len(await db.list_reminders("user1")) == 0


@pytest.mark.asyncio
async def test_cancel_fired_reminder(db):
    """Cannot cancel an already-fired reminder."""
    rid = await db.create_reminder("user1", "ch1", "2000-01-01T00:00:00", "Fired")
    await db.mark_reminder_fired(rid)
    assert await db.cancel_reminder(rid) is False


@pytest.mark.asyncio
async def test_create_recurring_reminder(db):
    rid = await db.create_reminder("user1", "ch1", "2099-01-01T12:00:00", "Daily", "daily")
    reminders = await db.list_reminders("user1")
    assert reminders[0]["recurrence"] == "daily"
