# REQ-005 Technical Design

> Status: Technical Finalized
> Requirement: requirement.md
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Technology Stack

| Module          | Technology                          | Rationale                                                           |
|:----------------|:------------------------------------|:--------------------------------------------------------------------|
| File write      | Python `pathlib` + stdlib           | Already used by local_files; consistent, no new dependency          |
| Shell execution | `asyncio.create_subprocess_shell()` | Async, non-blocking, built into Python stdlib                       |
| Safety          | `re` (regex pattern matching)       | Blacklist patterns are regex-based; stdlib, fast, no new dependency |
| Config          | `LOCAL_FILES_ALLOWED_PATHS` (.env)  | Reuse existing whitelist mechanism from local_files                 |

### New dependencies

None. All implementations use Python standard library only.

## 2. Design Principles

- **Extend, don't duplicate**: File write is added to the existing `local_files` tool, reusing `_is_allowed()`,
  `validate()`, and the whitelist infrastructure
- **Testable safety logic**: The blacklist check function `_is_blocked()` is a pure function (string in, bool out) that
  can be unit tested without executing any commands
- **Fail-safe defaults**: Shell timeout defaults to 30s; output capped at 10,000 chars; content write capped at 100KB
- **Single responsibility**: `local_files` handles all file I/O (read + write); `shell_exec` handles command execution
  with safety

## 3. Architecture Overview

```
apps/bot/tool/
├── local_files/
│   └── handler.py          ← MODIFIED: add write_file, append_file, mkdir
├── shell_exec/
│   ├── handler.py           ← NEW: shell execution tool
│   └── safety.py            ← NEW: blacklist patterns + _is_blocked()
├── brave_search/handler.py  (unchanged)
├── memo/handler.py          (unchanged)
├── task/handler.py          (unchanged)
├── reminder/handler.py      (unchanged)
└── mcp_server/handler.py    (unchanged)
```

Key point: `safety.py` is a separate module from `handler.py` so the blacklist logic can be imported and tested
independently.

## 4. Module Design

### 4.1 File Write Extensions (`apps/bot/tool/local_files/handler.py`)

- **Responsibility**: Extend existing local_files tool with write capabilities
- **Changes**:
    - Add `content` parameter to the tool's JSON Schema (`parameters`)
    - Add `write_file`, `append_file`, `mkdir` to the `action` enum
    - Update `description` and `usage_hint` to reflect new actions
    - Add constant `MAX_WRITE_BYTES = 102400` (100KB)
    - `execute()` routes new actions the same way as existing ones (guard clause pattern)
- **New methods**:
    ```python
    def _write_file(self, path: Path, content: str) -> str:
        """Create or overwrite a file. Auto-creates parent dirs."""

    def _append_file(self, path: Path, content: str) -> str:
        """Append content to file. Creates file if not exists."""

    def _mkdir(self, path: Path) -> str:
        """Create directory including intermediate dirs."""
    ```
- **Implementation details**:
    - `_write_file`: check content size → `path.parent.mkdir(parents=True, exist_ok=True)` →
      `path.write_text(content, encoding="utf-8")` → log INFO → return success message
    - `_append_file`: check content size → ensure parent dir → open with mode `"a"` encoding `"utf-8"` → log INFO →
      return success message
    - `_mkdir`: `path.mkdir(parents=True, exist_ok=True)` → log INFO → return success message
    - All three check `_is_allowed()` first (handled by existing `execute()` gate)
- **Reuse notes**: Shares `_is_allowed()`, `_allowed_roots`, `validate()` with read operations. No code duplication.

### 4.2 Shell Execution Tool (`apps/bot/tool/shell_exec/handler.py`)

- **Responsibility**: Execute shell commands asynchronously with safety checks and output formatting
- **Public interface**: Standard tool contract (`name`, `description`, `parameters`, `execute`)
- **Parameters schema**:
    ```json
    {
      "type": "object",
      "properties": {
        "command": {"type": "string", "description": "Shell command to execute"},
        "working_dir": {"type": "string", "description": "Working directory (optional, defaults to first allowed path)"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 120)"}
      },
      "required": ["command"]
    }
    ```
- **`execute()` flow**:
    1. Validate command is not empty
    2. Call `_is_blocked(command)` from `safety.py` — if blocked, return error with matched pattern
    3. Resolve working_dir (default: first `LOCAL_FILES_ALLOWED_PATHS` entry)
    4. Clamp timeout to [1, 120], default 30
    5. `asyncio.create_subprocess_shell(command, stdout=PIPE, stderr=PIPE, cwd=working_dir)`
    6. `await asyncio.wait_for(process.communicate(), timeout=timeout)`
    7. Decode stdout/stderr (handle binary with fallback)
    8. Truncate if combined output > `MAX_OUTPUT_CHARS` (10,000)
    9. Format and return result
- **`validate()`**: Check that `LOCAL_FILES_ALLOWED_PATHS` is set (needed for default working_dir). Parse and store
  `_allowed_roots` same as local_files, or reuse config directly.
- **Constants**:
    - `MAX_OUTPUT_CHARS = 10000`
    - `DEFAULT_TIMEOUT = 30`
    - `MAX_TIMEOUT = 120`

### 4.3 Shell Safety Module (`apps/bot/tool/shell_exec/safety.py`)

- **Responsibility**: Contain all blacklist patterns and the `_is_blocked()` pure function
- **Public interface**:
    ```python
    def is_blocked(command: str) -> tuple[bool, str]:
        """Check if a command matches any dangerous pattern.
        Returns (blocked: bool, matched_pattern: str).
        """
    ```
- **Blacklist patterns** (compiled regex list, as strict as possible):
    ```python
    _DANGEROUS_PATTERNS = [
        # ============================================================
        # 1. File / directory destruction
        # ============================================================
        (r"rm\s+.*-[a-zA-Z]*r", "recursive delete"),
        (r"rm\s+.*-[a-zA-Z]*f", "force delete"),
        (r"rmdir\s+/", "remove root directory"),
        (r"del\s+/[sS]", "Windows recursive delete"),
        (r"rd\s+/[sS]", "Windows recursive rmdir"),
        (r"find\s+.*-delete|-exec\s+rm", "find-and-delete"),
        (r"shred\s+", "secure file shred"),
        (r"wipe\s+", "disk/file wipe"),

        # ============================================================
        # 2. Disk / filesystem / partition
        # ============================================================
        (r"mkfs", "filesystem format"),
        (r"format\s+[A-Za-z]:", "Windows disk format"),
        (r"dd\s+", "raw disk operation"),
        (r"fdisk|parted|diskpart", "disk partitioning"),
        (r">\s*/dev/", "raw device write"),
        (r"mount\s+-o\s+remount|umount\s+/", "remount/unmount root"),
        (r"losetup|mdadm", "loop device / RAID manipulation"),
        (r"lvm|vgremove|lvremove|pvremove", "LVM destruction"),
        (r"swapoff\s+/|swapon\s+/dev/", "swap manipulation"),

        # ============================================================
        # 3. System control / services
        # ============================================================
        (r"shutdown|reboot|poweroff|halt|init\s+[0-6]", "system shutdown/reboot"),
        (r"systemctl\s+(stop|disable|mask|kill)", "systemctl service control"),
        (r"service\s+\S+\s+(stop|disable)", "service control"),
        (r"kill\s+-9\s+1\b|killall|pkill\s+-9", "kill system processes"),
        (r"telinit|runlevel", "runlevel change"),

        # ============================================================
        # 4. Permission / ownership
        # ============================================================
        (r"chmod\s+.*-[a-zA-Z]*R", "recursive permission change"),
        (r"chown\s+.*-[a-zA-Z]*R", "recursive ownership change"),
        (r"setfacl\s+.*-[a-zA-Z]*R", "recursive ACL change"),
        (r"chattr\s+.*-[a-zA-Z]*R", "recursive attribute change"),

        # ============================================================
        # 5. Privilege escalation
        # ============================================================
        (r"sudo\s+", "privilege escalation"),
        (r"su\s+-?\s*$|su\s+root", "switch to root"),
        (r"doas\s+", "privilege escalation (doas)"),
        (r"pkexec\s+", "polkit privilege escalation"),
        (r"runas\s+/user:", "Windows runas"),
        (r"passwd\s+", "password change"),
        (r"visudo|usermod|useradd|userdel|groupmod", "user/group management"),

        # ============================================================
        # 6. Network abuse
        # ============================================================
        (r"iptables\s+-[FX]|ufw\s+disable|firewall.*stop", "disable firewall"),
        (r"nc\s+-[a-zA-Z]*l|ncat\s+-[a-zA-Z]*l|socat\s+.*listen", "open network listener"),
        (r"ssh\s+-[a-zA-Z]*R\s|ssh\s+.*tunnel", "SSH reverse tunnel"),
        (r"nmap\s+|masscan\s+", "network scanning"),
        (r"tcpdump\s+|wireshark|tshark", "packet capture"),
        (r"arp\s+-[sd]|arping", "ARP manipulation"),
        (r"ifconfig\s+.*down|ip\s+link\s+set.*down", "disable network interface"),
        (r"route\s+(del|add)|ip\s+route\s+(del|add|flush)", "routing table manipulation"),

        # ============================================================
        # 7. Remote code / payload execution
        # ============================================================
        (r"curl\s+.*\|\s*(ba)?sh", "curl pipe to shell"),
        (r"wget\s+.*\|\s*(ba)?sh", "wget pipe to shell"),
        (r"curl\s+.*-o\s+/", "curl download to root"),
        (r"wget\s+.*-O\s+/", "wget download to root"),
        (r"python[23]?\s+-c\s+.*import\s+os", "python os module one-liner"),
        (r"perl\s+-e\s+.*system|ruby\s+-e\s+.*system", "script one-liner with system()"),
        (r"eval\s+\$\(|eval\s+`", "eval dynamic command"),
        (r"base64\s+.*-d\s*\|", "base64 decode pipe execution"),
        (r"xargs\s+.*rm|xargs\s+.*kill", "xargs destructive pipe"),

        # ============================================================
        # 8. Fork bomb / resource exhaustion
        # ============================================================
        (r":\(\)\s*\{", "fork bomb"),
        (r"while\s+true|for\s*\(\s*;\s*;\s*\)", "infinite loop"),
        (r"yes\s*\|", "yes pipe flooding"),
        (r"cat\s+/dev/zero|cat\s+/dev/urandom", "infinite data source"),
        (r"fallocate\s+.*-l\s+\d+[TG]", "large file allocation"),
        (r"head\s+-c\s+\d+[TG]", "huge data generation"),

        # ============================================================
        # 9. Dangerous moves / overwrites
        # ============================================================
        (r"mv\s+/\s", "move root directory"),
        (r"mv\s+.*\s+/dev/null", "move to /dev/null"),
        (r"cp\s+/dev/zero\s+|cp\s+/dev/urandom\s+", "overwrite with random/zero data"),
        (r">\s*/etc/|tee\s+/etc/", "overwrite system config"),

        # ============================================================
        # 10. Credential / key / config theft/tampering
        # ============================================================
        (r"cat\s+.*(id_rsa|id_ed25519|\.pem|\.key)", "read private key"),
        (r"cat\s+/etc/shadow|cat\s+/etc/passwd", "read system credentials"),
        (r"ssh-keygen\s+.*-f\s+/", "generate SSH key in system dir"),
        (r"git\s+config\s+.*credential", "git credential manipulation"),
        (r"cat\s+.*\.env\b|cat\s+.*\.netrc|cat\s+.*credentials", "read secret files"),
        (r"export\s+.*PASSWORD|export\s+.*SECRET|export\s+.*TOKEN", "export secrets to env"),

        # ============================================================
        # 11. History / log / audit tampering
        # ============================================================
        (r">\s*/var/log/|truncate.*log", "log tampering"),
        (r"history\s+-c|export\s+HISTSIZE=0|unset\s+HISTFILE", "history clearing"),
        (r"journalctl\s+--vacuum|logrotate\s+-f", "force log rotation/purge"),
        (r"auditctl\s+-D|auditctl\s+-e\s+0", "disable audit"),

        # ============================================================
        # 12. Crypto / ransomware patterns
        # ============================================================
        (r"openssl\s+enc\s+", "openssl encryption"),
        (r"gpg\s+--encrypt|gpg\s+-e", "GPG encryption"),
        (r"7z\s+a\s+.*-p|zip\s+.*-[eP]", "password-protected archive"),
        (r"tar\s+.*\|\s*openssl|tar\s+.*\|\s*gpg", "archive pipe to encryption"),

        # ============================================================
        # 13. Cron / scheduled tasks
        # ============================================================
        (r"crontab\s+-[re]", "crontab edit/remove"),
        (r"at\s+", "at scheduled job"),
        (r"schtasks\s+/(create|delete|change)", "Windows scheduled task"),

        # ============================================================
        # 14. Container / virtualization escape
        # ============================================================
        (r"docker\s+run\s+.*--privileged", "privileged container"),
        (r"docker\s+run\s+.*-v\s+/:/", "mount root into container"),
        (r"nsenter\s+", "namespace enter (container escape)"),
        (r"chroot\s+", "chroot"),

        # ============================================================
        # 15. Kernel / bootloader
        # ============================================================
        (r"insmod|rmmod|modprobe\s+-r", "kernel module manipulation"),
        (r"sysctl\s+-w", "kernel parameter change"),
        (r"grub|bcdedit|efibootmgr", "bootloader modification"),
        (r"dmesg\s+-C|dmesg\s+-c", "clear kernel ring buffer"),

        # ============================================================
        # 16. Windows-specific
        # ============================================================
        (r"reg\s+(delete|add)\s+HKLM", "Windows registry HKLM modification"),
        (r"reg\s+(delete|add)\s+HKCU", "Windows registry HKCU modification"),
        (r"wmic\s+", "WMI command"),
        (r"powershell\s+.*-[eE]ncodedCommand", "PowerShell encoded command"),
        (r"powershell\s+.*Invoke-Expression|powershell\s+.*iex", "PowerShell dynamic execution"),
        (r"net\s+user\s+|net\s+localgroup", "Windows user management"),
        (r"sc\s+(stop|delete|config)\s+", "Windows service control"),
        (r"cipher\s+/w:", "Windows secure wipe"),
        (r"vssadmin\s+delete", "Windows shadow copy delete"),
        (r"wevtutil\s+cl", "Windows event log clear"),
        (r"bitsadmin\s+/transfer", "BITS download"),
        (r"certutil\s+-urlcache", "certutil download"),
    ]
    ```
- **Design decisions**:
    - Patterns are compiled once at module load (`re.compile` with `re.IGNORECASE`)
    - The function is pure (no side effects) — string in, tuple out — trivially unit testable
    - Pattern list is intentionally conservative (blocks obvious destructive patterns, not subtle ones) — single-user
      trust model
- **Reuse notes**: Separated into its own module so it can be imported directly in tests without importing the full tool

### 4.4 Tool Description & Hint Updates

- **local_files**: Update `description` and `usage_hint` to mention write_file, append_file, mkdir
- **shell_exec**: `usage_hint = "Execute shell commands — run scripts, CLI tools, git, pip, etc."`
- No changes to `core/loader.py` or `core/mention.py` — the new tool is auto-discovered by `scan_tools()`

## 5. Data Model

No new data models or persistent storage. File write operates directly on the filesystem. Shell execution is stateless.

## 6. API Design

No HTTP APIs. All interfaces are Python method calls via the existing tool-call loop.

### Tool Schemas

**local_files (extended parameters)**:

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": [
        "search",
        "list_dir",
        "read_file",
        "file_info",
        "send_file",
        "write_file",
        "append_file",
        "mkdir"
      ]
    },
    "path": {
      "type": "string",
      "description": "Absolute file or directory path"
    },
    "query": {
      "type": "string",
      "description": "Search term (for search action)"
    },
    "content": {
      "type": "string",
      "description": "Text content to write (for write_file, append_file)"
    },
    "comment": {
      "type": "string",
      "description": "Optional comment (for send_file)"
    }
  },
  "required": [
    "action",
    "path"
  ]
}
```

**shell_exec**:

```json
{
  "type": "object",
  "properties": {
    "command": {
      "type": "string",
      "description": "Shell command to execute"
    },
    "working_dir": {
      "type": "string",
      "description": "Working directory (optional)"
    },
    "timeout": {
      "type": "integer",
      "description": "Timeout in seconds (default 30, max 120)"
    }
  },
  "required": [
    "command"
  ]
}
```

## 7. Key Flows

### 7.1 File Write Flow

```
AI calls local_files(action="write_file", path="/docs/report.txt", content="...")
  → execute() checks _is_allowed(path) → allowed
  → _write_file(path, content)
       → len(content.encode()) > MAX_WRITE_BYTES? → reject if so
       → path.parent.mkdir(parents=True, exist_ok=True)
       → path.write_text(content, encoding="utf-8")
       → logger.info("File written: %s (%d bytes)", path, size)
  → return "File written: report.txt (1234 bytes)"
```

### 7.2 Shell Execution Flow

```
AI calls shell_exec(command="git status", working_dir="/projects/myrepo")
  → execute() validates command not empty
  → safety.is_blocked("git status") → (False, "")
  → resolve working_dir, clamp timeout
  → asyncio.create_subprocess_shell("git status", cwd="/projects/myrepo", ...)
  → await wait_for(process.communicate(), timeout=30)
  → decode stdout + stderr
  → truncate if > 10000 chars
  → return "exit_code: 0\n--- stdout ---\nOn branch main\n..."
```

### 7.3 Blocked Command Flow

```
AI calls shell_exec(command="rm -rf /")
  → execute() validates command not empty
  → safety.is_blocked("rm -rf /") → (True, "recursive force delete on root")
  → logger.warning("Blocked command: %s (pattern: %s)", command, pattern)
  → return "Error: command blocked by safety policy — recursive force delete on root"
  → (command never executed)
```

## 8. Shared Modules & Reuse Strategy

| Shared Component                   | Used By                    | How                                                             |
|:-----------------------------------|:---------------------------|:----------------------------------------------------------------|
| `_is_allowed()` / `_allowed_roots` | local_files (read + write) | Existing whitelist check reused for all file operations         |
| `LOCAL_FILES_ALLOWED_PATHS`        | local_files, shell_exec    | shell_exec uses same config for default working_dir             |
| `safety.is_blocked()`              | shell_exec handler, tests  | Pure function in separate module; directly importable for tests |
| Tool auto-discovery                | All tools                  | `scan_tools()` picks up new shell_exec folder automatically     |

## 9. Risks & Notes

| Risk                                      | Mitigation                                                                                    |
|:------------------------------------------|:----------------------------------------------------------------------------------------------|
| AI writes sensitive content to file       | Path whitelist limits scope; single-user trust model                                          |
| Shell command does unexpected damage      | Blacklist blocks common destructive patterns; timeout prevents hangs; single-user trust model |
| Blacklist bypass via encoding/obfuscation | Accepted risk in single-user scenario; not attempting deep analysis                           |
| Large file write fills disk               | 100KB per-write cap; no multi-write flood protection (acceptable for single-user)             |
| Shell output contains sensitive data      | Output is shown only to the Discord user who invoked it; single-user scenario                 |
| Windows vs Linux shell differences        | Use system default shell; command compatibility is user's responsibility                      |
| Timeout kills long-running useful tasks   | Max 120s configurable by AI; user can ask AI to increase timeout                              |

## 10. Change Log

| Version | Date       | Changes                                                         | Affected Scope | Reason                            |
|:--------|:-----------|:----------------------------------------------------------------|:---------------|:----------------------------------|
| v1      | 2026-03-10 | Initial version                                                 | ALL            | -                                 |
| v2      | 2026-03-10 | Expand blacklist from 30 to 90+ patterns covering 16 categories | Section 4.3    | User requested maximum strictness |
