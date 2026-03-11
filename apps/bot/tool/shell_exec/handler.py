"""Shell command execution tool — run commands with safety checks.

Executes shell commands asynchronously with a dangerous-command blacklist,
configurable timeout, and output truncation. Uses the same
LOCAL_FILES_ALLOWED_PATHS as local_files for the default working directory.

Shell detection: picks the best available shell per platform at startup,
then all commands run through that shell uniformly via create_subprocess_exec.
"""

import asyncio
import logging
import shutil
import sys
from pathlib import Path

from apps.bot.config.settings import config
from apps.bot.tool.base import AnthropicTool, OpenAITool
from apps.bot.tool.shell_exec.safety import is_blocked

logger = logging.getLogger("synapulse.tool.shell_exec")

MAX_OUTPUT_CHARS = 10000
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Shell detection — one function, one responsibility
# ---------------------------------------------------------------------------

def _detect_shell() -> tuple[str, list[str]]:
    """Detect the best available shell for the current platform.

    Returns (executable_path, prefix_args) so the caller can do:
        subprocess_exec(executable, *prefix_args, command, ...)

    Windows : PowerShell 7+ (pwsh) → Windows PowerShell 5.1 (powershell)
    Unix    : bash → sh (POSIX fallback)
    """
    if sys.platform == "win32":
        for name in ("pwsh", "powershell"):
            path = shutil.which(name)
            if path:
                return path, ["-NoProfile", "-NonInteractive", "-Command"]
        # cmd.exe always exists — last resort
        return "cmd.exe", ["/c"]

    for name in ("bash", "sh"):
        path = shutil.which(name)
        if path:
            return path, ["-c"]

    return "/bin/sh", ["-c"]


# ---------------------------------------------------------------------------
# Platform-aware usage hints
# ---------------------------------------------------------------------------

_HINT_POWERSHELL = (
    "Shell is your primary tool for interacting with the system (PowerShell). "
    "Use it proactively:\n"
    "- Time/date: Get-Date, Get-Date -Format 'yyyy-MM-dd HH:mm:ss'\n"
    "- System info: systeminfo, Get-ComputerInfo, hostname, whoami\n"
    "- Disk/memory: Get-PSDrive, Get-Process | Sort-Object CPU -Desc | Select -First 10\n"
    "- Calculations: python -c \"print(...)\"\n"
    "- Network: Test-Connection -Count 1, Invoke-RestMethod <url>, curl <url>\n"
    "- Environment: $env:PATH, Get-ChildItem Env:, Get-Command <cmd>\n"
    "- Text processing: Get-Content, Select-String, Measure-Object\n"
    "- Package management: pip list, pip show, npm list\n"
    "- Git: git status, git log --oneline -5, git diff\n"
    "- Process info: Get-Process, tasklist, netstat -ano\n"
    "- Anything the OS can do — don't hesitate, just run it."
)

_HINT_UNIX = (
    "Shell is your primary tool for interacting with the system (bash). "
    "Use it proactively:\n"
    "- Time/date: date, cal, TZ=Asia/Shanghai date\n"
    "- System info: uname -a, df -h, free -h, uptime, whoami, hostname\n"
    "- Calculations: python3 -c 'print(...)' or echo '...' | bc\n"
    "- Network: ping -c1, curl -s <url>, wget\n"
    "- Environment: env, echo $PATH, which <cmd>\n"
    "- Text processing: wc, sort, head, tail, grep, awk\n"
    "- Package management: pip list, pip show, npm list\n"
    "- Git: git status, git log --oneline -5, git diff\n"
    "- Process info: ps aux, top -bn1, lsof\n"
    "- Anything the OS can do — don't hesitate, just run it."
)


class Tool(OpenAITool, AnthropicTool):
    name = "shell_exec"
    description = (
        "Execute a shell command and return its output. "
        "Use for running scripts, CLI tools (git, pip, curl, etc.), "
        "or any command-line operation. "
        "Dangerous commands (rm -rf, mkfs, shutdown, sudo, etc.) are blocked by safety policy."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "working_dir": {
                "type": "string",
                "description": (
                    "Working directory for the command (optional, "
                    "defaults to the first allowed path from LOCAL_FILES_ALLOWED_PATHS)"
                ),
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 30, max 120)",
            },
        },
        "required": ["command"],
    }
    usage_hint = ""  # set dynamically in validate() based on detected shell

    def validate(self) -> None:
        raw = config.LOCAL_FILES_ALLOWED_PATHS
        if not raw:
            raise EnvironmentError(
                "LOCAL_FILES_ALLOWED_PATHS is required for shell_exec tool. "
                "Set comma-separated allowed root paths in .env"
            )
        paths = [Path(p.strip()).resolve() for p in raw.split(",")]
        valid = [p for p in paths if p.is_dir()]
        if not valid:
            raise EnvironmentError("No valid directories in LOCAL_FILES_ALLOWED_PATHS")
        self._default_cwd = str(valid[0])

        # Detect shell once at startup — used for all subsequent executions
        self._shell_path, self._shell_args = _detect_shell()
        shell_name = Path(self._shell_path).stem
        logger.info("Detected shell: %s (%s)", shell_name, self._shell_path)
        logger.info("Default working directory: %s", self._default_cwd)

        # Set platform-aware usage hint so AI knows which commands to use
        self.usage_hint = _HINT_POWERSHELL if shell_name in ("pwsh", "powershell") else _HINT_UNIX

    async def execute(self, command: str = "", working_dir: str = "", timeout: int = DEFAULT_TIMEOUT) -> str:
        if not command or not command.strip():
            return "Error: command is required"

        # Safety check — pure function, no execution
        blocked, reason = is_blocked(command)
        if blocked:
            logger.warning("Blocked command: %s (reason: %s)", command, reason)
            return f"Error: command blocked by safety policy — {reason}"

        # Resolve working directory
        cwd = working_dir if working_dir else self._default_cwd
        cwd_path = Path(cwd)
        if not cwd_path.is_dir():
            return f"Error: working directory '{cwd}' does not exist"

        # Clamp timeout
        timeout = max(1, min(timeout, MAX_TIMEOUT))

        logger.info("Executing: %s (cwd=%s, timeout=%ds)", command, cwd, timeout)

        try:
            process = await asyncio.create_subprocess_exec(
                self._shell_path, *self._shell_args, command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            # Kill the process on timeout
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            logger.warning("Command timed out after %ds: %s", timeout, command)
            return f"Error: command timed out after {timeout}s"
        except Exception as e:
            logger.exception("Failed to execute command: %s", command)
            return f"Error: failed to execute command — {e}"

        # Decode output (handle binary gracefully)
        stdout = _decode_output(stdout_bytes)
        stderr = _decode_output(stderr_bytes)

        return _format_result(process.returncode, stdout, stderr)


def _decode_output(data: bytes) -> str:
    """Decode subprocess output, falling back to a binary-data notice."""
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode()  # system default encoding
    except UnicodeDecodeError:
        return f"(binary output, {len(data)} bytes)"


def _format_result(returncode: int | None, stdout: str, stderr: str) -> str:
    """Format subprocess result with optional truncation."""
    parts = [f"exit_code: {returncode}"]

    if stdout:
        parts.append(f"--- stdout ---\n{stdout.rstrip()}")
    if stderr:
        parts.append(f"--- stderr ---\n{stderr.rstrip()}")
    if not stdout and not stderr:
        parts.append("(no output)")

    result = "\n".join(parts)

    if len(result) > MAX_OUTPUT_CHARS:
        result = result[:MAX_OUTPUT_CHARS] + f"\n\n... (truncated, {len(result)} total characters)"

    return result
