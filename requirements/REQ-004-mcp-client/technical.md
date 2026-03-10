# REQ-004 Technical Design

> Status: Completed
> Requirement: requirement.md
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Technology Stack

| Module                     | Technology                                     | Rationale                                                                          |
|:---------------------------|:-----------------------------------------------|:-----------------------------------------------------------------------------------|
| MCP Client                 | `mcp` Python SDK (official, `pip install mcp`) | Mature official SDK, supports stdio transport, handles ClientSession lifecycle     |
| Process management         | `mcp.client.stdio` (`stdio_client`)            | SDK-provided async context manager for spawning and communicating with MCP servers |
| Static config              | JSON file (`apps/bot/config/mcp.json`)         | Standard MCP config format, consistent with ecosystem conventions                  |
| Dynamic config persistence | JSON file (`data/mcp_servers.json`)            | Under existing `.gitignore`-ed data directory, consistent with Database pattern    |

### New dependency

- `mcp` — official MCP Python SDK. This is the only new external package.

## 2. Design Principles

- **Dependency isolation**: `mcp/` module imports nothing from core/channel/provider/tool/job. Core orchestrates the MCP
  manager, not the other way around.
- **Reuse existing patterns**: MCP management tool follows `tool/{name}/handler.py` structure. MCP tools are formatted
  using the same `to_openai()` / `to_anthropic()` interface via wrapper objects.
- **Graceful degradation**: MCP failures never crash the bot. Individual server failures are isolated — other servers
  and native tools continue working.
- **Transparent integration**: AI sees one unified tool list. MCP tools are indistinguishable from native tools in the
  prompt and tool-call dispatch.
- **Dynamic tool list**: When MCP servers are added/removed, `provider.tools` is rebuilt. The tool-call loop in
  mention.py dispatches MCP tool calls to the MCP manager.

## 3. Architecture Overview

```
main.py → core/handler.py (bootstrap orchestrator)
               │
               ├── mcp/client.py           ← NEW: MCP connection manager
               │       ↑
               │       │
               ├── core/mention.py         ← MODIFIED: dispatch MCP tool calls
               │       │
               ├── core/loader.py          ← MODIFIED: merge MCP tools with native tools
               │       │
               ├── core/handler.py         ← MODIFIED: bootstrap MCP manager
               │
               ├── tool/mcp_server/handler.py  ← NEW: conversational MCP management tool
               ├── tool/brave_search/handler.py (unchanged)
               ├── tool/memo/handler.py         (unchanged)
               ├── tool/task/handler.py         (unchanged)
               │
               └── config/mcp.json         ← NEW: static MCP server config
```

Dependency direction — `mcp/` is a bottom layer like `memory/`:

```
core ──→ mcp/client    ←── tool/mcp_server
core ──→ memory        ←── tool/memo
core ──→ provider      (unchanged)
```

## 4. Module Design

### 4.1 MCP Client Manager (`apps/bot/mcp/client.py`)

- **Responsibility**: Manage MCP server connections, tool discovery, and tool execution
- **Public interface**:
    ```python
    class MCPManager:
        async def connect(self, name: str, config: dict) -> list[str]
        async def disconnect(self, name: str) -> bool
        async def disconnect_all(self) -> None
        def get_all_tools(self) -> list[MCPToolWrapper]
        async def call_tool(self, tool_name: str, arguments: dict) -> str
        def list_servers(self) -> list[dict]
        def list_tools(self, server_name: str | None = None) -> list[dict]
    ```
- **Internal structure**:
    - `_servers: dict[str, ServerEntry]` — registry of active connections
    - Each `ServerEntry` holds: `session` (ClientSession), `tools` (discovered tool list), `config` (original config
      dict), `read`/`write` (stdio transport streams)
    - `_tool_index: dict[str, str]` — maps `tool_name → server_name` for dispatch
    - `connect()` flow: validate config → `stdio_client(server_params)` → `ClientSession` → `session.initialize()` →
      `session.list_tools()` → register tools → update index
    - `call_tool()` flow: lookup server in `_tool_index` → `session.call_tool(name, arguments)` → extract text result
    - `disconnect()` flow: exit stdio context → remove from registry → update index
- **Tool name collision handling**: If an MCP server provides a tool with the same name as a native tool or another MCP
  tool, prefix with `mcp_{server}_` to avoid collision. The `_tool_index` always maps the final (possibly prefixed)
  name.
- **Reuse notes**: The MCPManager instance is created by core/handler.py and injected into the mcp_server tool and into
  the mention handler.

### 4.2 MCP Tool Wrapper (`apps/bot/mcp/client.py`)

- **Responsibility**: Wrap an MCP tool definition into the same format as native tools for provider integration
- **Public interface**:
    ```python
    class MCPToolWrapper:
        name: str
        description: str
        parameters: dict  # JSON Schema from MCP tool's inputSchema
        usage_hint: str

        def to_openai(self) -> dict
        def to_anthropic(self) -> dict
    ```
- **Internal structure**:
    - Constructed from MCP `Tool` objects returned by `session.list_tools()`
    - `to_openai()` and `to_anthropic()` produce the same format as native tool base classes
    - Not a subclass of `BaseTool` — does not need `execute()`, `validate()`, `db`, or `send_file`. It's a format
      adapter only.
- **Reuse notes**: Used by `loader.py`'s `format_tools_for_provider()` via duck typing (same `to_openai()` /
  `to_anthropic()` methods)

### 4.3 MCP Server Management Tool (`apps/bot/tool/mcp_server/handler.py`)

- **Responsibility**: AI tool for managing MCP servers via conversation
- **Public interface**: Standard tool contract (`name`, `description`, `parameters`, `execute`)
- **Actions**:
    - `add(name, command, args?, env?, timeout?)` → `mcp_manager.connect(...)` → persist to `data/mcp_servers.json` →
      report discovered tools
    - `remove(name)` → `mcp_manager.disconnect(...)` → remove from persisted config (if dynamic)
    - `list()` → `mcp_manager.list_servers()` → formatted server list with tool counts
    - `list_tools(name?)` → `mcp_manager.list_tools(name)` → formatted tool list
- **MCP Manager injection**: `mcp_manager` attribute set by core at startup (same pattern as `tool.db`)
- **Dynamic config persistence**:
    - On `add`: write updated config to `data/mcp_servers.json`
    - On `remove`: remove entry from `data/mcp_servers.json` (only for dynamic servers; static servers are only
      disconnected for this session)
    - Config file format: same `{"mcpServers": {...}}` structure as static config
- **Rebuild trigger**: After `add` or `remove`, the tool signals core to rebuild the provider's tool list. This is done
  via a callback `_rebuild_tools` injected by core.
- **Validation**: `validate()` is no-op (mcp_manager injected after scan, same pattern as memo/reminder)
- **Guard rails**:
    - Server limit: `_MAX_SERVERS = 20` — check before add
    - Name validation: alphanumeric + underscore only

### 4.4 Bootstrap Changes (`apps/bot/core/handler.py`)

- **Responsibility**: Extended to create MCPManager, load configs, connect servers, inject into tool and mention handler
- **Changes**:
    - After `db.init()`, create `MCPManager` instance
    - Load static config from `apps/bot/config/mcp.json` (optional file)
    - Load dynamic config from `data/mcp_servers.json` (optional file, under DATABASE_PATH parent)
    - Merge configs (dynamic overrides static for same name)
    - Connect to all configured servers (failures logged, not fatal)
    - After `scan_tools()`, inject `mcp_manager` into the mcp_server tool
    - Define `rebuild_tools()` callback that re-merges native + MCP tools and updates `provider.tools`
    - Inject `_rebuild_tools` callback into the mcp_server tool
    - Call `rebuild_tools()` once initially to set up the merged tool list
    - On shutdown (finally block), call `mcp_manager.disconnect_all()`
- **New helper in handler.py**:
    ```python
    def _load_mcp_config(path: str) -> dict:
        """Load MCP config from JSON file. Returns empty dict on missing/invalid file."""
    ```

### 4.5 Loader Changes (`apps/bot/core/loader.py`)

- **Responsibility**: Extended to merge MCP tool wrappers with native tools for formatting
- **Changes**:
    - New function `merge_tools_for_provider(native_tools, mcp_tools, api_format) -> list[dict]`
    - Iterates native tools using existing `format_tools_for_provider()` logic
    - Appends MCP tool wrappers using their `to_{api_format}()` methods
    - New function `merge_tool_hints(native_tools, mcp_tools) -> str` to include MCP tool hints in system prompt
- **Reuse notes**: `format_tools_for_provider()` and `format_tool_hints()` remain unchanged. New functions compose them.

### 4.6 Mention Handler Changes (`apps/bot/core/mention.py`)

- **Responsibility**: Extended to dispatch MCP tool calls to the MCP manager
- **Changes**:
    - `make_mention_handler()` receives new optional parameter `mcp_manager: MCPManager | None = None`
    - In the tool-call loop, when `tools.get(call.name)` returns `None`, check if `mcp_manager` has the tool before
      returning "unknown tool"
    - MCP tool dispatch: `result = await mcp_manager.call_tool(call.name, call.arguments)`
    - MCP tool calls still go through JSON Schema validation (schema is in the MCPToolWrapper)
    - MCP tool names are tracked in `tool_names_used` the same as native tools
- **MCP tool schema lookup**: The mention handler needs access to MCP tool schemas for validation. This is done via a
  `mcp_tools_dict: dict[str, MCPToolWrapper]` passed alongside `mcp_manager`, or by adding a `get_tool_schema(name)`
  method to MCPManager.

### 4.7 Config File (`apps/bot/config/mcp.json`)

- **Responsibility**: Static MCP server configuration
- **Format**: Standard MCP config convention
    ```json
    {
      "mcpServers": {
        "server_name": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-xxx", "/path"],
          "env": {},
          "timeout": 30000
        }
      }
    }
    ```
- **Behavior**: Optional file. If missing or empty, bot starts normally with no MCP servers.
- **Location**: Alongside other config files in `apps/bot/config/`

## 5. Data Model

### Static Config: `apps/bot/config/mcp.json`

Top-level object with `mcpServers` key. Each server entry:

| Field     | Type         | Description                                        |
|:----------|:-------------|:---------------------------------------------------|
| `command` | string       | Executable to spawn (e.g., "npx", "python")        |
| `args`    | list[string] | Command arguments                                  |
| `env`     | object       | Environment variables for the process              |
| `timeout` | int          | Connection timeout in milliseconds (default 30000) |

### Dynamic Config: `data/mcp_servers.json`

Same format as static config. Persists servers added via chat.

### Internal: ServerEntry (in-memory only)

| Field     | Type                 | Description                                   |
|:----------|:---------------------|:----------------------------------------------|
| `name`    | string               | Server identifier                             |
| `session` | ClientSession        | Active MCP session                            |
| `tools`   | list[MCPToolWrapper] | Discovered tools from this server             |
| `config`  | dict                 | Original config (command, args, env, timeout) |
| `source`  | string               | "static" or "dynamic"                         |

### Internal: Tool Index (in-memory only)

| Field | Type   | Description                         |
|:------|:-------|:------------------------------------|
| key   | string | Tool name (possibly prefixed)       |
| value | string | Server name that provides this tool |

## 6. API Design

No HTTP APIs. All interfaces are Python method calls within the same process.

### Tool Schema (JSON Schema for AI function calling)

**mcp_server tool:**

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["add", "remove", "list", "list_tools"],
      "description": "Action to perform"
    },
    "name": {
      "type": "string",
      "description": "Server name (for add, remove, list_tools)"
    },
    "command": {
      "type": "string",
      "description": "Command to run the MCP server (for add)"
    },
    "args": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Command arguments (for add)"
    },
    "env": {
      "type": "object",
      "description": "Environment variables (for add)"
    },
    "timeout": {
      "type": "integer",
      "description": "Connection timeout in milliseconds (for add, default 30000)"
    }
  },
  "required": ["action"]
}
```

## 7. Key Flows

### 7.1 Startup — Static + Dynamic Config Loading

```
main.py → handler.start()
  → MCPManager()
  → _load_mcp_config("apps/bot/config/mcp.json")    → static servers
  → _load_mcp_config("data/mcp_servers.json")        → dynamic servers
  → merge configs (dynamic overrides static for same name)
  → for each server:
       mcp_manager.connect(name, config)
         → stdio_client(StdioServerParameters(command, args, env))
         → ClientSession(read, write)
         → session.initialize()
         → session.list_tools()
         → register tools, update tool_index
       (on failure: log warning, continue with next)
  → scan_tools() → inject mcp_manager into mcp_server tool
  → rebuild_tools() → merge native + MCP tools → provider.tools
  → channel.run(on_mention=make_mention_handler(provider, tools, ..., mcp_manager))
```

### 7.2 Conversational Server Add

```
User: "connect a GitHub MCP server"
  → AI calls mcp_server.add(name="github", command="npx", args=[...])
  → tool: mcp_manager.connect("github", config)
       → stdio_client → ClientSession → initialize → list_tools
       → (success) register tools, update tool_index
  → tool: persist config to data/mcp_servers.json
  → tool: _rebuild_tools() → re-merge tools → provider.tools updated
  → tool returns: "Connected server 'github'. Discovered 15 tools: ..."
  → AI reports to user
```

### 7.3 MCP Tool Call During Conversation

```
User @mentions bot with a question
  → mention handler builds prompt (MCP tools included in tool list)
  → AI decides to call an MCP tool (e.g., "github_create_issue")
  → tool-call loop: tools.get("github_create_issue") → None (not native)
  → check mcp_manager: has tool "github_create_issue" → yes
  → mcp_manager.call_tool("github_create_issue", arguments)
       → lookup server in tool_index → "github"
       → session.call_tool("github_create_issue", arguments)
       → extract text content from result
  → append tool result to messages
  → AI continues (may call more tools or return text)
```

### 7.4 MCP Server Disconnect

```
User: "disconnect the filesystem server"
  → AI calls mcp_server.remove(name="filesystem")
  → tool: mcp_manager.disconnect("filesystem")
       → exit stdio context, cleanup session
       → remove from _servers and _tool_index
  → tool: if dynamic, remove from data/mcp_servers.json
  → tool: _rebuild_tools() → re-merge tools → provider.tools updated
  → tool returns: "Disconnected server 'filesystem'"
```

## 8. Shared Modules & Reuse Strategy

| Shared Component                           | Used By                          | How                                                                              |
|:-------------------------------------------|:---------------------------------|:---------------------------------------------------------------------------------|
| `to_openai()` / `to_anthropic()` interface | MCPToolWrapper, all native tools | Duck typing — MCPToolWrapper implements same methods without inheriting BaseTool |
| `format_tools_for_provider()`              | handler.py (via loader.py)       | Extended with `merge_tools_for_provider()` that composes native + MCP            |
| `format_tool_hints()`                      | handler.py (via loader.py)       | Extended with `merge_tool_hints()` for MCP tool hints                            |
| `tool.mcp_manager` injection pattern       | handler.py → mcp_server tool     | Same IoC pattern as `tool.db` injection                                          |
| `_load_json` / `_save_json` pattern        | MCPManager config persistence    | Same JSON file I/O pattern as Database class                                     |
| JSON Schema validation in mention.py       | Both native and MCP tools        | MCPToolWrapper provides `parameters` (from MCP inputSchema) for validation       |

## 9. Risks & Notes

| Risk                                       | Mitigation                                                                                                                            |
|:-------------------------------------------|:--------------------------------------------------------------------------------------------------------------------------------------|
| MCP server process hangs or crashes        | Per-server timeout (configurable, default 30s). Catch exceptions, mark server disconnected, return error to AI                        |
| stdio pipe blocks on large output          | MCP SDK handles buffering internally. Timeout protects against indefinite blocks                                                      |
| `npx` or other commands not found          | Return clear error message: "Failed to start server: command not found"                                                               |
| MCP SDK version incompatibility            | Pin `mcp` version in requirements. SDK follows semver                                                                                 |
| Tool name collision (MCP vs native)        | Auto-prefix with `mcp_{server}_` when collision detected                                                                              |
| Too many MCP tools overwhelm the AI        | Practical limit enforced by _MAX_SERVERS (20 servers). Each server typically provides 5-20 tools. This is within model context limits |
| Dynamic config file corruption             | Write atomically (write to temp file, rename). Invalid JSON on load → skip dynamic config, log warning                                |
| MCP server provides no tools               | Connected but inactive. Log info, include in server list with tool count 0                                                            |
| Secrets in env variables persisted to disk | `data/` directory is in `.gitignore`. User should be aware env vars are written to disk                                               |

## 10. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version | ALL            | -      |
