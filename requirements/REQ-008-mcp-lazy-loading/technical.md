# REQ-008 Technical Design

> Status: Development Done
> Requirement: requirement.md
> Created: 2026-03-11
> Updated: 2026-03-11

## 1. Technology Stack

| Module             | Technology       | Rationale                             |
|:-------------------|:-----------------|:--------------------------------------|
| Core orchestration | Python asyncio   | Existing architecture                 |
| MCP client         | mcp SDK (stdio)  | Already integrated in REQ-004         |
| GitHub API         | aiohttp          | Already used by provider, lazy import |
| Config             | YAML + dataclass | Existing models.yaml pattern          |

## 2. Design Principles

- High cohesion, low coupling: each change is contained within its module boundary
- Zero-config where possible: auto-detect over manual configuration
- Fail-safe: all new features degrade gracefully on error
- Token-conscious: minimize API payload size without losing capability

## 3. Architecture Overview

The lazy loading mechanism spans three layers:

```
System Prompt (hints) ←── loader.py: merge_tool_hints()
         ↓
AI sees MCP tool names, calls mcp_server(action="use_tools")
         ↓
mention.py: detect activation → add schemas to provider.tools
         ↓
Next round: AI has schemas, calls MCP tools directly
         ↓
mention.py: dispatch to mcp_manager.call_tool()
```

## 4. Module Design

### 4.1 On-Demand Loading (mention.py)

- Responsibility: Track activated MCP tool schemas per request, augment provider.tools
- Changes:
    - Save `original_tools = provider.tools` at loop start
    - Maintain `active_mcp_schemas: list[dict]` per request
    - Before each `chat()`, set `provider.tools = original_tools + active_mcp_schemas`
    - After `mcp_server` tool call with `action="use_tools"`, call `_activate_mcp_tools()`
    - Restore `provider.tools = original_tools` in `finally` block
- New function: `_activate_mcp_tools(requested_names, mcp_manager, api_format, active_schemas)`
    - Looks up wrappers via `mcp_manager.get_tools_by_names()`
    - Formats via `to_{api_format}()` and appends to active_schemas
    - Deduplicates by tool name

### 4.2 Tool Hints (loader.py)

- Responsibility: Build system prompt text listing MCP tools with activation instructions
- Changes to `merge_tool_hints()`:
    - Native tools: same format as before (`- name: hint`)
    - MCP tools: separate section with instruction text
    - Uses `description` (not `usage_hint`) for MCP tools — more informative for AI

### 4.3 Tool List Building (handler.py)

- Responsibility: `rebuild_tools()` only includes native tools in `provider.tools`
- Changes:
    - Import `format_tools_for_provider` instead of `merge_tools_for_provider`
    - `provider.tools = format_tools_for_provider(tools, provider.api_format)`
    - MCP tool hints still built via `merge_tool_hints(tools, mcp_tools)`

### 4.4 MCP Tool Activation (mcp_server/handler.py)

- Responsibility: `use_tools` action validates tool names and returns confirmation
- Changes:
    - Add `"use_tools"` to action enum
    - Add `"tools"` parameter (array of strings)
    - `_use_tools()` method: validate names against `mcp_manager.get_all_tools()`, return found/not-found

### 4.5 Tool Name Lookup (mcp/client.py)

- Responsibility: Look up MCP tool wrappers by name
- New method: `get_tools_by_names(names: list[str]) -> list[MCPToolWrapper]`
    - Uses `_tool_index` for O(1) server lookup per name

### 4.6 Result Truncation (mention.py + base.py + models.py)

- `EndpointConfig.max_result_chars: int = 16000` — configurable per endpoint in YAML
- `BaseProvider._max_result_chars: int = 16000` — updated by `_http_chat()` from current endpoint
- `BaseProvider.max_result_chars` property — read by mention.py
- mention.py: after tool execution, truncate result if `len(result) > provider.max_result_chars`

### 4.7 Owner Auto-Detection (handler.py + prompts.py)

- `_detect_owner_context(mcp_manager)` — called after MCP connect, before rebuild_tools
    - Checks for GitHub MCP server with `search_users` tool
    - Extracts PAT from server config env
    - Calls `GET /user` via aiohttp
    - Writes to `prompts.runtime_context["github_owner"]`
- `prompts.runtime_context: dict[str, list[str]]` — module-level dict, injected into system prompt by
  `build_system_prompt()`

### 4.8 MCP Env Expansion & Stability (handler.py + client.py)

- `_expand_mcp_env()` — resolves `${VAR}` in server env configs
    - Called at startup before connect
    - Called in hot-reload loop before change detection
- `_get_enabled_servers()` — adds `isinstance(cfg, dict)` check for `_comment` entries
- `client.py` disconnect — catches `(Exception, BaseException)` for anyio errors
- `client.py` connect — Windows command resolution via `shutil.which()`, env merging

## 5. Data Model

No database changes. `EndpointConfig` dataclass gains one field:

```python
@dataclass(frozen=True)
class EndpointConfig:
    ...
    max_result_chars: int = 16000
```

## 6. API Design

No external APIs. Internal tool action added:

| Action                           | Parameters         | Response                       |
|:---------------------------------|:-------------------|:-------------------------------|
| `mcp_server(action="use_tools")` | `tools: list[str]` | "Activated N MCP tool(s): ..." |

## 7. Key Flows

### On-Demand MCP Tool Loading Flow

1. AI receives system prompt with MCP tool hints (names only)
2. AI calls `mcp_server(action="use_tools", tools=["search_repositories"])`
3. `mcp_server._use_tools()` validates names, returns confirmation
4. mention.py detects `use_tools` action, calls `_activate_mcp_tools()`
5. `_activate_mcp_tools()` gets wrappers from MCPManager, formats schemas, adds to `active_mcp_schemas`
6. Next round: `provider.tools = original_tools + active_mcp_schemas`
7. AI calls `search_repositories(...)` with full schema
8. mention.py dispatches to `mcp_manager.call_tool()`
9. Result truncated if exceeds `max_result_chars`, then appended to messages

### Owner Auto-Detection Flow

1. MCP servers connected at startup
2. `_detect_owner_context()` checks for GitHub MCP
3. Extracts PAT from server config
4. `GET /user` → `{login: "GOODDAYDAY", name: "GoodyHao"}`
5. Injects into `runtime_context["github_owner"]`
6. `build_system_prompt()` includes owner lines in every prompt

## 8. Shared Modules & Reuse Strategy

| Component                                   | Used By                | Purpose                                                           |
|:--------------------------------------------|:-----------------------|:------------------------------------------------------------------|
| `MCPToolWrapper.to_openai()/to_anthropic()` | mention.py, loader.py  | Format MCP schemas for any provider                               |
| `mcp_manager.get_tools_by_names()`          | mention.py             | New method, reusable for any name-based lookup                    |
| `prompts.runtime_context`                   | handler.py, prompts.py | Generic runtime context injection, extensible for future services |
| `EndpointConfig.max_result_chars`           | base.py, mention.py    | Per-model config pattern, reusable for other limits               |

## 9. Risks & Notes

- `provider.tools` is mutated per-request (save/restore pattern) — safe for single-threaded asyncio but would need locks
  for concurrent requests
- GitHub user detection depends on server name being "github" — different MCP configs may use other names
- `runtime_context` is module-level mutable state — acceptable for single-instance bot

## 10. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-11 | Initial version | ALL            | -      |
