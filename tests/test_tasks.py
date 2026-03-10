"""Tests for task database methods and task tool — covers REQ-003 AC-01 to AC-05."""

import os
import tempfile

import pytest
import pytest_asyncio

from apps.bot.memory.database import Database
from apps.bot.tool.task.handler import Tool as TaskTool


@pytest_asyncio.fixture
async def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        database = Database()
        await database.init(db_path)
        yield database
        await database.close()


@pytest_asyncio.fixture
async def task_tool(db):
    tool = TaskTool()
    tool.db = db
    return tool


# --- Database layer tests ---

@pytest.mark.asyncio
async def test_save_and_list_tasks(db):
    """AC-01: Create a task and list it."""
    task_id = await db.save_task("user1", "Submit report", priority="high", due_date="2026-03-14")
    assert task_id >= 1

    tasks = await db.list_tasks("user1")
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Submit report"
    assert tasks[0]["priority"] == "high"
    assert tasks[0]["due_date"] == "2026-03-14"
    assert tasks[0]["status"] == "todo"


@pytest.mark.asyncio
async def test_list_tasks_excludes_done(db):
    """Default list excludes completed tasks."""
    await db.save_task("user1", "Task A")
    task_id = await db.save_task("user1", "Task B")
    await db.complete_task(task_id)

    tasks = await db.list_tasks("user1")
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Task A"


@pytest.mark.asyncio
async def test_list_tasks_filter_done(db):
    """Can explicitly list completed tasks."""
    await db.save_task("user1", "Task A")
    task_id = await db.save_task("user1", "Task B")
    await db.complete_task(task_id)

    done = await db.list_tasks("user1", status="done")
    assert len(done) == 1
    assert done[0]["title"] == "Task B"


@pytest.mark.asyncio
async def test_list_tasks_sorted_by_priority(db):
    """Tasks sorted by priority: high > medium > low."""
    await db.save_task("user1", "Low task", priority="low")
    await db.save_task("user1", "High task", priority="high")
    await db.save_task("user1", "Medium task", priority="medium")

    tasks = await db.list_tasks("user1")
    assert tasks[0]["title"] == "High task"
    assert tasks[1]["title"] == "Medium task"
    assert tasks[2]["title"] == "Low task"


@pytest.mark.asyncio
async def test_update_task(db):
    """Update specific fields of a task."""
    task_id = await db.save_task("user1", "Old title")
    updated = await db.update_task(task_id, title="New title", priority="high")
    assert updated is True

    tasks = await db.list_tasks("user1")
    assert tasks[0]["title"] == "New title"
    assert tasks[0]["priority"] == "high"


@pytest.mark.asyncio
async def test_update_nonexistent_task(db):
    """Update returns False for missing task."""
    result = await db.update_task(999, title="Nope")
    assert result is False


@pytest.mark.asyncio
async def test_complete_task(db):
    """AC-03: Mark a task as done."""
    task_id = await db.save_task("user1", "Finish homework")
    completed = await db.complete_task(task_id)
    assert completed is True

    # Not in default list
    tasks = await db.list_tasks("user1")
    assert len(tasks) == 0

    # In done list
    done = await db.list_tasks("user1", status="done")
    assert len(done) == 1


@pytest.mark.asyncio
async def test_delete_task(db):
    """Delete a task permanently."""
    task_id = await db.save_task("user1", "Temp task")
    deleted = await db.delete_task(task_id)
    assert deleted is True

    deleted_again = await db.delete_task(task_id)
    assert deleted_again is False


@pytest.mark.asyncio
async def test_delete_nonexistent_task(db):
    result = await db.delete_task(999)
    assert result is False


@pytest.mark.asyncio
async def test_get_pending_tasks_summary(db):
    """Get pending tasks for context injection."""
    await db.save_task("user1", "Task A", priority="low")
    await db.save_task("user1", "Task B", priority="high")
    task_id = await db.save_task("user1", "Task C")
    await db.complete_task(task_id)

    pending = await db.get_pending_tasks_summary("user1")
    assert len(pending) == 2
    # High priority first
    assert pending[0]["title"] == "Task B"


@pytest.mark.asyncio
async def test_tasks_isolated_by_user(db):
    """Different users have separate task lists."""
    await db.save_task("user1", "User1 task")
    await db.save_task("user2", "User2 task")

    tasks1 = await db.list_tasks("user1")
    tasks2 = await db.list_tasks("user2")
    assert len(tasks1) == 1
    assert len(tasks2) == 1
    assert tasks1[0]["title"] == "User1 task"


# --- Tool layer tests ---

@pytest.mark.asyncio
async def test_tool_create(task_tool):
    """AC-01: Create task via tool."""
    result = await task_tool.execute(action="create", title="Submit report", priority="high", due_date="2026-03-14")
    assert "Created task #" in result
    assert "Submit report" in result
    assert "high priority" in result


@pytest.mark.asyncio
async def test_tool_list(task_tool):
    """AC-02: List tasks via tool."""
    await task_tool.execute(action="create", title="Task A", priority="high")
    await task_tool.execute(action="create", title="Task B", priority="low")
    result = await task_tool.execute(action="list")
    assert "Task A" in result
    assert "Task B" in result


@pytest.mark.asyncio
async def test_tool_complete(task_tool):
    """AC-03: Complete task via tool."""
    result = await task_tool.execute(action="create", title="Finish work")
    # Extract task id from "Created task #N"
    task_id = int(result.split("#")[1].split(":")[0])
    result = await task_tool.execute(action="complete", task_id=task_id)
    assert "marked as done" in result


@pytest.mark.asyncio
async def test_tool_delete(task_tool):
    """AC-04: Delete task via tool."""
    result = await task_tool.execute(action="create", title="Temp task")
    task_id = int(result.split("#")[1].split(":")[0])
    result = await task_tool.execute(action="delete", task_id=task_id)
    assert "Deleted task" in result


@pytest.mark.asyncio
async def test_tool_update(task_tool):
    result = await task_tool.execute(action="create", title="Old title")
    task_id = int(result.split("#")[1].split(":")[0])
    result = await task_tool.execute(action="update", task_id=task_id, title="New title", priority="high")
    assert "Updated task" in result
    assert "title=New title" in result


@pytest.mark.asyncio
async def test_tool_create_missing_title(task_tool):
    result = await task_tool.execute(action="create")
    assert "Error" in result


@pytest.mark.asyncio
async def test_tool_create_invalid_priority(task_tool):
    result = await task_tool.execute(action="create", title="Test", priority="urgent")
    assert "Error" in result
    assert "invalid priority" in result


@pytest.mark.asyncio
async def test_tool_duplicate_detection(task_tool):
    await task_tool.execute(action="create", title="Buy groceries")
    result = await task_tool.execute(action="create", title="buy groceries")
    assert "similar task already exists" in result


@pytest.mark.asyncio
async def test_tool_complete_nonexistent(task_tool):
    result = await task_tool.execute(action="complete", task_id=999)
    assert "not found" in result


@pytest.mark.asyncio
async def test_tool_list_empty(task_tool):
    result = await task_tool.execute(action="list")
    assert "No tasks found" in result


@pytest.mark.asyncio
async def test_tool_list_filter_by_status(task_tool):
    await task_tool.execute(action="create", title="Task A")
    result = await task_tool.execute(action="create", title="Task B")
    task_id = int(result.split("#")[1].split(":")[0])
    await task_tool.execute(action="complete", task_id=task_id)

    # Default: only pending
    result = await task_tool.execute(action="list")
    assert "Task A" in result
    assert "Task B" not in result

    # Explicit done filter
    result = await task_tool.execute(action="list", status="done")
    assert "Task B" in result


@pytest.mark.asyncio
async def test_tool_no_db(task_tool):
    """Tool without db returns error."""
    task_tool.db = None
    result = await task_tool.execute(action="list")
    assert "Error" in result
