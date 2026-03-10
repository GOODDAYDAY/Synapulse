"""Task tool — persistent to-do list and task tracking for the user.

Lets the AI create, list, update, complete, and delete tasks.
All data persisted in JSON files via the injected Database instance.
"""

import logging

from apps.bot.tool.base import AnthropicTool, OpenAITool

logger = logging.getLogger("synapulse.tool.task")

_DEFAULT_USER = "default"
_MAX_TASKS = 500
_VALID_STATUSES = {"todo", "in_progress", "done"}
_VALID_PRIORITIES = {"low", "medium", "high"}


class Tool(OpenAITool, AnthropicTool):
    name = "task"
    description = (
        "Manage user tasks and to-do items. "
        "Actions: create (add a new task), list (show tasks), "
        "update (modify a task), complete (mark done), delete (remove a task)."
    )
    usage_hint = (
        "Track to-dos, action items, and deadlines. "
        "Use when the user asks to add, check, update, or complete tasks. "
        "Do not create tasks for every request — only when user explicitly asks."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "update", "complete", "delete"],
                "description": (
                    "create: add a new task; "
                    "list: show tasks (default: pending only); "
                    "update: modify task fields; "
                    "complete: mark a task as done; "
                    "delete: permanently remove a task"
                ),
            },
            "task_id": {
                "type": "integer",
                "description": "Task ID (for update, complete, delete)",
            },
            "title": {
                "type": "string",
                "description": "Task title (for create, update)",
            },
            "description": {
                "type": "string",
                "description": "Task description (for create, update)",
            },
            "status": {
                "type": "string",
                "enum": ["todo", "in_progress", "done"],
                "description": "Task status (for list filter, update)",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Task priority (for create, update, list filter). Default: medium",
            },
            "due_date": {
                "type": "string",
                "description": "Due date in ISO 8601 format, e.g. 2026-03-14 (for create, update)",
            },
        },
        "required": ["action"],
    }

    def validate(self) -> None:
        # db is injected by core after scan_tools(), so not available here.
        pass

    async def execute(
            self, action: str, task_id: int = 0,
            title: str = "", description: str = "",
            status: str = "", priority: str = "",
            due_date: str = "",
    ) -> str:
        if not self.db:
            return "Error: database not available"
        if action == "create":
            return await self._create(title, description, priority, due_date)
        if action == "list":
            return await self._list(status, priority)
        if action == "update":
            return await self._update(task_id, title, description, status, priority, due_date)
        if action == "complete":
            return await self._complete(task_id)
        if action == "delete":
            return await self._delete(task_id)
        return f"Error: unknown action '{action}'"

    async def _create(self, title: str, description: str, priority: str, due_date: str) -> str:
        if not title:
            return "Error: 'title' is required for create action"

        # Validate priority
        prio = priority or "medium"
        if prio not in _VALID_PRIORITIES:
            return f"Error: invalid priority '{prio}'. Must be: low, medium, high"

        # Check task limit
        existing = await self.db.list_tasks(_DEFAULT_USER, status=None, limit=_MAX_TASKS)
        # Count all tasks including done
        all_tasks = await self.db.list_tasks(_DEFAULT_USER, status="done", limit=_MAX_TASKS)
        total = len(existing) + len(all_tasks)
        if total >= _MAX_TASKS:
            return f"Error: task limit reached ({_MAX_TASKS}). Please delete old tasks first."

        # Check for duplicates (case-insensitive title match on pending tasks)
        for t in existing[:50]:
            if t["title"].strip().lower() == title.strip().lower():
                return f"A similar task already exists: #{t['id']} — {t['title']}"

        task_id = await self.db.save_task(
            _DEFAULT_USER, title,
            description=description or "",
            priority=prio,
            due_date=due_date or None,
        )
        due_note = f", due {due_date}" if due_date else ""
        logger.info("Created task #%d: %s", task_id, title)
        return f"Created task #{task_id}: {title} ({prio} priority{due_note})"

    async def _list(self, status: str, priority: str) -> str:
        # Validate filter values
        if status and status not in _VALID_STATUSES:
            return f"Error: invalid status '{status}'. Must be: todo, in_progress, done"
        if priority and priority not in _VALID_PRIORITIES:
            return f"Error: invalid priority '{priority}'. Must be: low, medium, high"

        tasks = await self.db.list_tasks(
            _DEFAULT_USER,
            status=status or None,
            priority=priority or None,
        )
        if not tasks:
            filter_desc = ""
            if status:
                filter_desc += f" with status={status}"
            if priority:
                filter_desc += f" with priority={priority}"
            return f"No tasks found{filter_desc}."

        lines = []
        for t in tasks:
            due = f" [due {t['due_date']}]" if t.get("due_date") else ""
            prio = f" ({t['priority']})" if t["priority"] != "medium" else ""
            status_icon = {"todo": "[ ]", "in_progress": "[~]", "done": "[x]"}.get(t["status"], "[ ]")
            lines.append(f"{status_icon} #{t['id']}{prio}{due} {t['title']}")
        return "\n".join(lines)

    async def _update(
            self, task_id: int, title: str, description: str,
            status: str, priority: str, due_date: str,
    ) -> str:
        if not task_id:
            return "Error: 'task_id' is required for update action"

        # Validate values
        if status and status not in _VALID_STATUSES:
            return f"Error: invalid status '{status}'. Must be: todo, in_progress, done"
        if priority and priority not in _VALID_PRIORITIES:
            return f"Error: invalid priority '{priority}'. Must be: low, medium, high"

        # Build update fields (only non-empty values)
        fields = {}
        if title:
            fields["title"] = title
        if description:
            fields["description"] = description
        if status:
            fields["status"] = status
        if priority:
            fields["priority"] = priority
        if due_date:
            fields["due_date"] = due_date

        if not fields:
            return "Error: no fields to update. Provide at least one of: title, description, status, priority, due_date"

        updated = await self.db.update_task(task_id, **fields)
        if updated:
            logger.info("Updated task #%d: %s", task_id, list(fields.keys()))
            return f"Updated task #{task_id}: {', '.join(f'{k}={v}' for k, v in fields.items())}"
        return f"Task #{task_id} not found."

    async def _complete(self, task_id: int) -> str:
        if not task_id:
            return "Error: 'task_id' is required for complete action"
        completed = await self.db.complete_task(task_id)
        if completed:
            logger.info("Completed task #%d", task_id)
            return f"Task #{task_id} marked as done."
        return f"Task #{task_id} not found."

    async def _delete(self, task_id: int) -> str:
        if not task_id:
            return "Error: 'task_id' is required for delete action"
        deleted = await self.db.delete_task(task_id)
        if deleted:
            logger.info("Deleted task #%d", task_id)
            return f"Deleted task #{task_id}."
        return f"Task #{task_id} not found."
