"""Tests for core/reminder.py — covers AC-07 (reminder fires after restart)."""

import os
import tempfile

import pytest
import pytest_asyncio

from apps.bot.core.reminder import _fire_reminder
from apps.bot.memory.database import Database


@pytest_asyncio.fixture
async def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        database = Database()
        await database.init(db_path)
        yield database
        await database.close()


@pytest.mark.asyncio
async def test_fire_reminder(db):
    """AC-07: Reminder fires correctly."""
    rid = await db.create_reminder("user1", "ch1", "2000-01-01T00:00:00", "Test reminder")
    due = await db.get_due_reminders()
    assert len(due) == 1

    fired_messages = []

    async def mock_notify(channel_id, message):
        fired_messages.append((channel_id, message))

    await _fire_reminder(db, mock_notify, due[0])

    assert len(fired_messages) == 1
    assert fired_messages[0][0] == "ch1"
    assert "Test reminder" in fired_messages[0][1]

    # Should be marked as fired
    remaining = await db.get_due_reminders()
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_fire_overdue_reminder_has_delayed_tag(db):
    """Overdue reminders get [Delayed] prefix."""
    await db.create_reminder("user1", "ch1", "2000-01-01T00:00:00", "Old reminder")
    due = await db.get_due_reminders()

    fired_messages = []

    async def mock_notify(channel_id, message):
        fired_messages.append(message)

    await _fire_reminder(db, mock_notify, due[0])
    assert "[Delayed]" in fired_messages[0]


@pytest.mark.asyncio
async def test_fire_recurring_reminder_creates_next(db):
    """Recurring reminders create the next occurrence after firing."""
    await db.create_reminder("user1", "ch1", "2000-01-01T12:00:00", "Daily task", "daily")
    due = await db.get_due_reminders()

    async def mock_notify(channel_id, message):
        pass

    await _fire_reminder(db, mock_notify, due[0])

    # Should have created a new reminder for the next day
    reminders = await db.list_reminders("user1")
    assert len(reminders) == 1
    assert reminders[0]["message"] == "Daily task"
    assert "2000-01-02" in reminders[0]["remind_at"]


@pytest.mark.asyncio
async def test_fire_failure_does_not_mark_fired(db):
    """If notification fails, reminder stays unfired."""
    await db.create_reminder("user1", "ch1", "2000-01-01T00:00:00", "Fail test")
    due = await db.get_due_reminders()

    async def failing_notify(channel_id, message):
        raise ConnectionError("Channel unavailable")

    await _fire_reminder(db, failing_notify, due[0])

    # Should still be due (not marked as fired)
    remaining = await db.get_due_reminders()
    assert len(remaining) == 1
