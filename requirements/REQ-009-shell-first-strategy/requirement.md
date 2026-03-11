# REQ-009: Shell-First Behavior Strategy

## Status: Completed

## Created: 2026-03-11

## Author: User + Claude

---

## 1. Background & Problem

### Current Situation

The `shell_exec` tool is positioned as a **fallback** in the behavior strategy (`prompts.py`):
> "If a dedicated tool fails or is unavailable, try shell_exec as fallback"

This causes the AI to almost never proactively use bash, even for tasks where bash is the simplest and most direct
solution.

### Pain Points

1. **Time/Date queries**: AI guesses or says "I don't know" instead of running `date`
2. **System information**: AI says "I cannot access" instead of running `uname`, `df`, `whoami`, etc.
3. **Quick calculations**: AI calculates manually instead of using `python3 -c` or `bc`
4. **Data retrieval**: AI doesn't use `curl` for quick API calls, or `cat`/`head` for file previews
5. **Process/environment info**: AI can't tell the user about running processes, env vars, disk space, etc.
6. **Glue operations**: bash can chain tools together (pipes, redirections) — this power is wasted

### Root Cause

The behavior strategy treats `shell_exec` as a last resort rather than a **primary capability**. The AI needs explicit
guidance to use bash proactively for tasks where it's the most efficient tool.

---

## 2. Requirements

### REQ-009-01: Elevate shell_exec to First-Class Tool

- **Remove** the "fallback" framing from `BEHAVIOR_STRATEGY`
- **Add** explicit guidance for when to use `shell_exec` **proactively** (not as fallback)
- Shell should be the go-to tool for: time/date, system info, quick calculations, environment queries, process
  management, file operations that local_files can't do, and any task that's simplest via CLI

### REQ-009-02: Update shell_exec Usage Hint

- The current `usage_hint` is too generic: "Execute shell commands — run scripts, CLI tools, git, pip, etc."
- Update to include concrete examples of proactive use cases:
    - Time/date (`date`, `cal`)
    - System info (`uname`, `df`, `free`, `uptime`)
    - Quick calculations (`python3 -c`, `bc`)
    - Network checks (`ping`, `curl`)
    - Environment (`env`, `whoami`, `hostname`)
    - Text processing (`wc`, `sort`, `head`, `tail`)

### REQ-009-03: Restructure BEHAVIOR_STRATEGY

Reorganize the strategy section to clearly separate tool routing:

- **Direct knowledge**: General knowledge, opinions, casual chat → no tools
- **Memory**: Explicit remember/recall requests → `memo`
- **Reminders**: Time-based → `reminder`
- **Tasks**: Explicit tracking → `task`
- **Real-time info**: Current events, news → `brave_search`
- **Weather**: Weather queries → `weather` (dedicated, richer output)
- **Shell (PRIMARY)**: Time, date, system info, calculations, CLI operations, file manipulation, process info,
  environment queries, package management, git operations → `shell_exec`
- **Files**: Read/write/search files in allowed paths → `local_files`
- Shell is NOT a fallback — it's a primary tool for anything the system can do

### REQ-009-04: Preserve Existing Behavior

- Do NOT change the tool implementations themselves (shell_exec, local_files, etc.)
- Do NOT change the safety blacklist
- Do NOT change the tool-call loop in `core/mention.py`
- Only modify prompt/guidance text in `prompts.py`
- Only modify `usage_hint` in `shell_exec/handler.py`

---

## 3. Scope

### In Scope

| File                                  | Change                                             |
|---------------------------------------|----------------------------------------------------|
| `apps/bot/config/prompts.py`          | Rewrite `BEHAVIOR_STRATEGY` to promote shell-first |
| `apps/bot/tool/shell_exec/handler.py` | Update `usage_hint` with concrete examples         |

### Out of Scope

- Tool implementation changes
- Safety blacklist changes
- New tools
- Core/loader changes

---

## 4. Acceptance Criteria

1. `BEHAVIOR_STRATEGY` no longer describes `shell_exec` as a "fallback"
2. `shell_exec` has a rich `usage_hint` with concrete example commands
3. The strategy clearly guides the AI to use bash proactively for system queries, time, calculations, etc.
4. All existing behavior guidance (memo, reminder, task, search, weather) is preserved
5. No code logic changes — only prompt/hint text changes

---

## Change Log

| Version | Date       | Description   |
|---------|------------|---------------|
| 1.0     | 2026-03-11 | Initial draft |
