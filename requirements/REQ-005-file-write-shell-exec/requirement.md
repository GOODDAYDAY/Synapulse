# REQ-005 File Write & Shell Execution

> Status: Requirement Finalized
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Background

Synapulse's AI currently has read-only file access (`local_files`) and web search (`brave_search`), but cannot write
files or execute commands. This severely limits the assistant's practical capabilities — it cannot generate reports,
modify configs, run scripts, or invoke CLI tools. Additionally, a large portion of the OpenClaw community skills depend
on bash/file-write capabilities; adding these abilities enables broader ecosystem compatibility.

Browser capability is already covered via MCP (puppeteer/playwright in mcp.json) and is out of scope.

## 2. Target Users & Scenarios

- **User**: Project author (single-user personal assistant)
- **Scenarios**:
    - "Save this content to D:\docs\notes.txt"
    - "Create a new file config.yaml under D:\projects with the following content..."
    - "Run `git status` to check the current repo state"
    - "Execute `pip list` to see installed packages"
    - "Run `python scripts/analyze.py` and tell me the result"
    - "Append the analysis result to the end of report.txt"

## 3. Functional Requirements

### F-01 File Write (Extend local_files Tool)

- **Main flow**:
    - Add 3 new actions to the existing `local_files` tool: `write_file`, `append_file`, `mkdir`
    - `write_file(path, content)` — create or overwrite a file with text content
    - `append_file(path, content)` — append content to the end of an existing file (create if not exists)
    - `mkdir(path)` — create a directory (including intermediate directories)
    - All write operations are constrained by the `LOCAL_FILES_ALLOWED_PATHS` whitelist, sharing the same
      `_is_allowed()` check as read operations
    - Write encoding: UTF-8
    - Automatically create parent directories if they don't exist
- **Error handling**:
    - Path outside whitelist → "Error: path is outside allowed directories"
    - Permission denied → "Error: permission denied"
    - Disk full → "Error: disk full" (catch OSError)
- **Edge cases**:
    - Writing empty content → creates an empty file (valid operation)
    - Target already exists (write_file) → overwrite directly (no confirmation; AI should judge on its own)
    - Very large content → limit single write to 100KB; reject if exceeded
    - Path with special characters → delegate to OS, catch exceptions

### F-02 Shell Execution (New shell_exec Tool)

- **Main flow**:
    - New tool at `apps/bot/tool/shell_exec/handler.py`
    - `execute(command, working_dir?, timeout?)` — execute a shell command, return stdout + stderr
    - Default working_dir: the first path in `LOCAL_FILES_ALLOWED_PATHS`
    - Default timeout: 30 seconds, maximum 120 seconds
    - Use `asyncio.create_subprocess_shell()` for async execution
    - Output format: `exit_code: N\n--- stdout ---\n...\n--- stderr ---\n...`
    - Output truncation: truncate when stdout + stderr exceeds 10,000 characters, with a note
- **Error handling**:
    - Command timeout → kill the process, return "Error: command timed out after Xs"
    - Command not found → return shell's stderr (e.g., "command not found")
    - Process abnormal exit → return exit code + stderr
- **Edge cases**:
    - Interactive commands (e.g., `vim`, `python` with no args) → timeout kills them
    - Binary output → attempt decode, on failure return "(binary output, N bytes)"
    - Empty command → "Error: command is required"

### F-03 Shell Safety Mechanism

- **Main flow**:
    - Dangerous command blacklist: patterns matching `rm -rf /`, `mkfs`, `format C:`, `shutdown`, `reboot`, `dd if=`,
      fork bombs, etc.
    - Pre-execution check: pattern match on the full command string; block if matched
    - Working directory: defaults to a whitelisted path; does not sandbox `cd` (relies on user trust in single-user
      scenario)
    - Environment variables: inherit current process env, no extra injection
- **Error handling**:
    - Blacklist hit → "Error: command blocked by safety policy — [matched pattern]"
- **Edge cases**:
    - Piped commands `echo foo | rm -rf /` → blacklist checks the entire command string
    - Variable expansion `$HOME` → shell handles it; no pre-processing
    - Encoded bypass attempts (base64 tricks, etc.) → no deep analysis; single-user trust model

## 4. Non-functional Requirements

- **Security**: File writes constrained by path whitelist; shell has dangerous command blacklist and timeout
- **Architecture consistency**:
    - File write: extends existing `local_files` tool, no new tool created
    - Shell execution: new `tool/shell_exec/handler.py`, follows standard tool structure
    - No new external dependencies (uses Python stdlib `asyncio.subprocess`)
- **Performance**: Shell commands execute asynchronously, non-blocking; timeout auto-kills
- **Logging**: All write operations and command executions logged at INFO level; blocked commands logged at WARNING
- **Testing**: Dangerous command tests are unit tests on the blacklist matching function only — never execute real
  dangerous commands. All integration tests use safe commands (`echo`, `ls`, `git status`). Tests must clean up any
  files/directories they create.

## 5. Out of Scope

- File deletion (`delete_file` / `delete_dir`) — high risk, deferred
- Command whitelist mode (only allow specific commands) — blacklist sufficient for single-user
- Sandbox / container isolation — not needed for single-user personal assistant
- Browser tool — already covered via MCP (puppeteer/playwright)
- Windows-specific shell compatibility (PowerShell vs cmd) — use system default shell
- Concurrent command execution — one command at a time

## 6. Acceptance Criteria

| ID    | Feature | Condition                                                   | Expected Result                                             |
|:------|:--------|:------------------------------------------------------------|:------------------------------------------------------------|
| AC-01 | F-01    | AI writes content to a file under a whitelisted path        | File created successfully with correct content              |
| AC-02 | F-01    | AI appends content to an existing file                      | Original content preserved, new content appended at the end |
| AC-03 | F-01    | AI writes to a path outside the whitelist                   | Error returned, file not created                            |
| AC-04 | F-01    | AI creates a directory (including nested)                   | Directory created successfully                              |
| AC-05 | F-01    | Write content exceeding 100KB                               | Error returned, file not created                            |
| AC-06 | F-02    | AI executes `echo hello`                                    | Returns exit_code: 0, stdout: hello                         |
| AC-07 | F-02    | AI executes `git status` in a project directory             | Returns git status output                                   |
| AC-08 | F-02    | Command timeout (e.g., `sleep 999`)                         | Returns timeout error after 30 seconds                      |
| AC-09 | F-02    | Command produces very long output                           | Output truncated to 10,000 chars with note                  |
| AC-10 | F-03    | Unit test: `_is_blocked("rm -rf /")` returns True           | Blacklist function correctly identifies dangerous command   |
| AC-11 | F-03    | Unit test: `_is_blocked("mkfs.ext4 /dev/sda")` returns True | Blacklist function correctly identifies dangerous command   |
| AC-12 | F-02    | AI specifies working_dir for a command                      | Command executes in the specified directory                 |
| AC-13 | F-03    | Unit test: `_is_blocked("echo hello")` returns False        | Normal commands are not falsely blocked                     |

## 7. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version | ALL            | -      |
