"""Local file access — read and write within allowed directories.

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
MAX_WRITE_BYTES = 102400  # 100KB per write
MAX_LIST_ENTRIES = 100
MAX_SEARCH_RESULTS = 50

# Directories that clutter results and are never what the user wants.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".cache"}


class Tool(OpenAITool, AnthropicTool):
    name = "local_files"
    description = (
        "Access and manage local files. "
        "Read: search, list_dir, read_file, file_info, send_file. "
        "Write: write_file (create/overwrite), append_file (append), mkdir (create directory).\n"
        "All operations are restricted to allowed directories."
    )
    usage_hint = (
        "Files and directories — search to find, list_dir to browse, "
        "read_file to read, write_file to create/overwrite, append_file to append, "
        "mkdir to create directories, send_file to send as attachment."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "search", "list_dir", "read_file", "file_info", "send_file",
                    "write_file", "append_file", "mkdir",
                ],
                "description": (
                    "search: find files/dirs by name recursively (use query param); "
                    "list_dir: list one directory; "
                    "read_file: read text file; "
                    "file_info: metadata; "
                    "send_file: send file as attachment; "
                    "write_file: create or overwrite a file (use content param); "
                    "append_file: append to a file (use content param); "
                    "mkdir: create directory (including parents)"
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
            "content": {
                "type": "string",
                "description": "Text content to write (required for write_file, append_file)",
            },
            "comment": {
                "type": "string",
                "description": "Optional comment when sending a file (used with send_file action)",
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

    async def execute(self, action: str, path: str, query: str = "", content: str = "", comment: str = "") -> str:
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
        if action == "send_file":
            return await self._send_file(target, comment)
        if action == "write_file":
            return self._write_file(target, content)
        if action == "append_file":
            return self._append_file(target, content)
        if action == "mkdir":
            return self._mkdir(target)

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

    async def _send_file(self, path: Path, comment: str) -> str:
        if not path.is_file():
            return f"Error: '{path}' is not a file"
        if not self.send_file:
            return "Error: file sending is not available in this channel"
        await self.send_file(str(path), comment)
        return f"File sent: {path.name}"

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

    # --- Write operations ---

    def _write_file(self, path: Path, content: str) -> str:
        """Create or overwrite a file with text content. Auto-creates parent dirs."""
        size = len(content.encode("utf-8"))
        if size > MAX_WRITE_BYTES:
            return f"Error: content too large ({size} bytes, max {MAX_WRITE_BYTES})"

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except PermissionError:
            return f"Error: permission denied for '{path}'"
        except OSError as e:
            return f"Error: failed to write file — {e}"

        logger.info("File written: %s (%d bytes)", path, size)
        return f"File written: {path.name} ({size} bytes)"

    def _append_file(self, path: Path, content: str) -> str:
        """Append content to a file. Creates the file if it doesn't exist."""
        size = len(content.encode("utf-8"))
        if size > MAX_WRITE_BYTES:
            return f"Error: content too large ({size} bytes, max {MAX_WRITE_BYTES})"

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
        except PermissionError:
            return f"Error: permission denied for '{path}'"
        except OSError as e:
            return f"Error: failed to append to file — {e}"

        logger.info("Content appended: %s (%d bytes)", path, size)
        return f"Content appended to {path.name} ({size} bytes)"

    def _mkdir(self, path: Path) -> str:
        """Create a directory including intermediate directories."""
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            return f"Error: permission denied for '{path}'"
        except OSError as e:
            return f"Error: failed to create directory — {e}"

        logger.info("Directory created: %s", path)
        return f"Directory created: {path}"
