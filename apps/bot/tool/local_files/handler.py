"""Local file browser — read-only access to allowed directories.

Design principle: code does traversal (mechanical), AI does matching (decision).
- list_dir: one level at a time — AI decides where to drill down next.
- search: code does recursive traversal — AI only judges the results.
This keeps each tool result small so the AI can reason clearly at every step.
"""

import logging
import os
from datetime import datetime
from pathlib import Path

from apps.bot.config.settings import config
from apps.bot.tool.base import AnthropicTool, OpenAITool

logger = logging.getLogger("synapulse.tool.local_files")

MAX_READ_CHARS = 10000
MAX_LIST_ENTRIES = 100
MAX_SEARCH_RESULTS = 50

# Directories that clutter results and are never what the user wants.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".cache"}


class Tool(OpenAITool, AnthropicTool):
    name = "local_files"
    description = (
        "Access local files. "
        "Use search to find files by name across directories (one call). "
        "Use list_dir to browse one directory at a time.\n"
        "Actions: search, list_dir, read_file, file_info."
    )
    usage_hint = (
        "Files and directories — use search to find files by name, "
        "list_dir to browse, read_file to read content."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "list_dir", "read_file", "file_info"],
                "description": (
                    "search: find files/dirs by name recursively (use query param); "
                    "list_dir: list one directory; "
                    "read_file: read text file; "
                    "file_info: metadata"
                ),
            },
            "path": {
                "type": "string",
                "description": "Absolute file or directory path",
            },
            "query": {
                "type": "string",
                "description": "Search term for file/directory name (required for search action)",
            },
        },
        "required": ["action", "path"],
    }

    def validate(self) -> None:
        raw = config.LOCAL_FILES_ALLOWED_PATHS
        if not raw:
            raise EnvironmentError(
                "LOCAL_FILES_ALLOWED_PATHS is required for local_files tool. "
                "Set comma-separated allowed root paths in .env"
            )
        self._allowed_roots: list[Path] = []
        for p in raw.split(","):
            root = Path(p.strip()).resolve()
            if not root.is_dir():
                raise EnvironmentError(f"Allowed path does not exist: {root}")
            self._allowed_roots.append(root)
        logger.info("Allowed roots: %s", [str(r) for r in self._allowed_roots])

    def _is_allowed(self, path: Path) -> bool:
        """Check resolved path is within allowed roots (prevents .. escape)."""
        resolved = path.resolve()
        for root in self._allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    async def execute(self, action: str, path: str, query: str = "") -> str:
        target = Path(path)

        if not self._is_allowed(target):
            return f"Error: path '{path}' is outside allowed directories"

        if action == "search":
            return self._search(target, query)
        if action == "list_dir":
            return self._list_dir(target)
        if action == "read_file":
            return self._read_file(target)
        if action == "file_info":
            return self._file_info(target)

        return f"Error: unknown action '{action}'"

    def _search(self, path: Path, query: str) -> str:
        """Recursive file name search — code traverses, AI judges results."""
        if not query:
            return "Error: 'query' parameter is required for search action"
        if not path.is_dir():
            return f"Error: '{path}' is not a directory"

        query_lower = query.lower()
        matches = []

        for root, dirs, files in os.walk(path):
            # Prune junk directories so os.walk won't descend into them.
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

            for name in dirs + files:
                if query_lower in name.lower():
                    entry = Path(root) / name
                    kind = "dir" if entry.is_dir() else "file"
                    matches.append(f"[{kind}] {entry}")

            if len(matches) >= MAX_SEARCH_RESULTS:
                matches = matches[:MAX_SEARCH_RESULTS]
                break

        if not matches:
            return f"No files matching '{query}' found under '{path}'"

        result = "\n".join(matches)
        if len(matches) >= MAX_SEARCH_RESULTS:
            result += f"\n\n... (showing first {MAX_SEARCH_RESULTS} matches, there may be more)"
        return result

    def _list_dir(self, path: Path) -> str:
        if not path.is_dir():
            return f"Error: '{path}' is not a directory"

        try:
            items = sorted(path.iterdir())
        except PermissionError:
            return f"Error: permission denied for '{path}'"

        # Filter out junk directories that clutter results.
        items = [e for e in items if not (e.is_dir() and e.name in _SKIP_DIRS)]
        total = len(items)
        items = items[:MAX_LIST_ENTRIES]

        lines = []
        for entry in items:
            kind = "dir" if entry.is_dir() else "file"
            lines.append(f"[{kind}] {entry.name}")

        if not lines:
            return "(empty directory)"

        result = "\n".join(lines)
        if total > MAX_LIST_ENTRIES:
            result += f"\n\n... (showing {MAX_LIST_ENTRIES} of {total} entries)"
        return result

    def _read_file(self, path: Path) -> str:
        if not path.is_file():
            return f"Error: '{path}' is not a file"

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = path.read_text()  # system default encoding (GBK on zh-CN Windows)
            except Exception:
                return f"Error: '{path.name}' is not a readable text file"
        except PermissionError:
            return f"Error: permission denied for '{path}'"

        if len(text) > MAX_READ_CHARS:
            return text[:MAX_READ_CHARS] + f"\n\n... (truncated, {len(text)} total characters)"
        return text

    def _file_info(self, path: Path) -> str:
        if not path.exists():
            return f"Error: '{path}' does not exist"

        try:
            stat = path.stat()
        except PermissionError:
            return f"Error: permission denied for '{path}'"

        kind = "directory" if path.is_dir() else "file"
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return f"type: {kind}\nsize: {stat.st_size} bytes\nmodified: {modified}"
