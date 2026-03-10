# REQ-008 MCP On-Demand Tool Loading & Token Optimization

> Status: Development Done
> Created: 2026-03-11
> Updated: 2026-03-11

## 1. Background

After REQ-004 integrated MCP with 55+ pre-configured servers, enabling just 3 servers (github, puppeteer, fetch) exposed
34 MCP tools. Combined with 8 native tools, the 42 tool schemas exceeded the GitHub Models free tier 8000-token limit,
causing HTTP 413 errors on every AI request.

Additionally, MCP tool results (e.g. GitHub search returning 21K chars) frequently exceeded context limits even when
requests succeeded.

A secondary issue: the system prompt contained hardcoded owner identity (GitHub username), which should be auto-detected
from connected MCP services rather than configured manually.

## 2. Target Users & Scenarios

- Bot users with limited-context AI endpoints (GitHub Models free tier, small local models)
- Bot users with multiple MCP servers enabled simultaneously
- Any deployment where tool count exceeds provider token limits

## 3. Functional Requirements

### F-01 On-Demand MCP Tool Schema Loading

- Main flow:
    1. At startup, only native tool schemas are sent in the API `tools` parameter
    2. MCP tool names and descriptions are listed in the system prompt as hints
    3. The hint text instructs AI to call `mcp_server(action="use_tools", tools=[...])` to activate MCP tools
    4. When AI calls `use_tools`, the mention handler detects this and adds the requested MCP tool schemas to the API
       tools list
    5. On the next round, AI has full schemas and can call MCP tools directly
    6. Activated schemas persist for the duration of the current request only
- Error handling:
    - If requested tool names don't exist, return error listing available tools
    - If no tools parameter provided, return error message
    - Duplicate activation requests are silently deduplicated
- Edge cases:
    - No MCP servers connected → no MCP hints in system prompt, `use_tools` returns error
    - All MCP tools already activated → no-op, no duplicate schemas

### F-02 Tool Result Truncation with Per-Model Limits

- Main flow:
    1. `EndpointConfig` gains a `max_result_chars` field (default: 16000)
    2. Configurable per endpoint in `models.yaml` (e.g. `max_result_chars: 8000` for GitHub Models)
    3. After each tool execution, if result exceeds the limit, truncate and append a notice
    4. The truncation limit is read from the provider's last-used endpoint
- Error handling:
    - If endpoint has no `max_result_chars`, default 16000 is used
- Edge cases:
    - Result exactly at limit → not truncated
    - Mock provider (no pool) → uses default 16000

### F-03 Auto-Detect Owner Identity from GitHub MCP

- Main flow:
    1. After MCP servers connect at startup, check if GitHub MCP is available
    2. Extract PAT from the GitHub server's expanded env config
    3. Call `GET https://api.github.com/user` with the PAT to get `login` and `name`
    4. Inject owner info into system prompt via `runtime_context` dict in prompts.py
    5. AI sees `Owner's GitHub username: XXX (use user:XXX when searching their repositories)`
- Error handling:
    - GitHub MCP not connected → skip silently
    - PAT empty or invalid → skip with warning log
    - Network timeout (10s) → skip with warning log
- Edge cases:
    - GitHub API returns user with no `name` field → only inject `login`
    - MCP server name is not "github" → detection skipped (keyed on server name)

### F-04 MCP Environment Variable Expansion & Hot-Reload Fixes

- Main flow:
    1. `_expand_mcp_env()` resolves `${VAR}` references in MCP server env configs at startup
    2. Same expansion applied in the hot-reload loop to prevent false change detection
    3. `_get_enabled_servers()` filters out non-dict entries (e.g. `_comment` strings)
- Error handling:
    - Missing env var → expanded to empty string
    - Non-dict config entries → filtered out silently

### F-05 MCP Connection Stability Improvements

- Main flow:
    1. Windows: resolve command names via `shutil.which()` for subprocess_exec compatibility
    2. MCP subprocess env merges system env with config env to preserve PATH
    3. Disconnect catches `BaseException` (not just `Exception`) to handle anyio cancel scope errors
    4. GITHUB_PAT separated from GITHUB_TOKEN for MCP-specific authentication
- Error handling:
    - Command not found after resolution → normal connection error, logged and skipped
    - Disconnect error → logged as warning, does not crash bot

### F-06 Enable Pre-Configured MCP Servers

- Main flow:
    1. Enable github, puppeteer, fetch servers in `config/mcp.json`
    2. Use direct installed commands instead of `npx -y` to avoid download delays
    3. GitHub server uses `${GITHUB_PAT}` env var for authentication
- Edge cases:
    - Servers not installed locally → connection fails at startup, logged and skipped

## 4. Non-functional Requirements

- Token usage reduced from 42 tool schemas to 8 native schemas per request
- MCP tool activation adds only the requested schemas (1-5 typically), not all 34
- Tool result truncation prevents context overflow on any model size
- Auto-detection adds zero configuration overhead for owner identity
- All edge cases fail silently with logging — never crash the bot

## 5. Out of Scope

- Anthropic provider chat implementation (deferred)
- MCP tool caching across requests (schemas are per-request only)
- Dynamic `max_result_chars` adjustment based on remaining context budget
- Browser/puppeteer MCP tool testing

## 6. Acceptance Criteria

| ID    | Feature | Condition                             | Expected Result                                                                   |
|:------|:--------|:--------------------------------------|:----------------------------------------------------------------------------------|
| AC-01 | F-01    | AI needs an MCP tool                  | AI calls `mcp_server(action="use_tools")`, then uses activated tool in next round |
| AC-02 | F-01    | No MCP servers connected              | System prompt has no MCP hints, native tools work normally                        |
| AC-03 | F-01    | Duplicate activation                  | No duplicate schemas in tools list                                                |
| AC-04 | F-02    | Tool returns 21K chars, limit is 8000 | Result truncated to 8000 + notice                                                 |
| AC-05 | F-02    | `max_result_chars` not in YAML        | Default 16000 used                                                                |
| AC-06 | F-03    | GitHub MCP connected with valid PAT   | Owner username auto-injected in prompt                                            |
| AC-07 | F-03    | GitHub MCP not connected              | No owner info in prompt, no error                                                 |
| AC-08 | F-04    | MCP config has `${GITHUB_PAT}`        | Expanded to actual env value before connection                                    |
| AC-09 | F-04    | Hot-reload reads config               | Env vars expanded, no false change detection                                      |
| AC-10 | F-05    | Windows + npx command                 | Resolved via shutil.which() to full path                                          |
| AC-11 | F-05    | MCP disconnect with anyio error       | Caught as warning, bot continues                                                  |
| AC-12 | F-06    | Bot starts with github MCP enabled    | GitHub MCP connects, tools discovered                                             |

## 7. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-11 | Initial version | ALL            | -      |
