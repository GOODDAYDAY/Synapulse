# REQ-004 MCP Client Integration

> Status: Completed
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Background

Synapulse currently has 5 hand-written tools (brave_search, local_files, memo, reminder, task). Adding each new
capability requires writing a `tool/{name}/handler.py` from scratch. Meanwhile, the MCP (Model Context Protocol)
ecosystem already has hundreds of ready-made tool servers — Google Calendar, Notion, GitHub, filesystem, databases, and
more. By implementing MCP client support, Synapulse can instantly access this entire ecosystem without writing
tool-specific code.

MCP is an open protocol published by Anthropic. The official Python SDK (`pip install mcp`) is mature and supports stdio
and HTTP transports. This requirement adds MCP client support via two configuration paths: a static config file for
pre-set servers, and a conversational tool for managing servers through Discord chat.

## 2. Target Users & Scenarios

- **User**: Project author (single-user personal assistant)
- **Scenarios**:
    - Pre-configured servers: user sets up MCP servers in a config file, bot auto-connects on startup
    - Conversational management: user tells AI "connect a GitHub MCP server" → AI adds and connects it
    - Tool discovery: user asks "what MCP tools do I have?" → AI lists all connected servers and their tools
    - Seamless usage: AI calls MCP tools alongside native tools transparently — user doesn't need to know which is which
    - Dynamic management: user says "disconnect the filesystem server" → AI removes it

## 3. Functional Requirements

### F-01 MCP Server Configuration (Static)

- **Main flow**:
    - New config file `apps/bot/config/mcp.json` defining pre-set MCP servers
  - Pre-configured with 55 popular MCP servers (GitHub, Notion, filesystem, databases, DevOps, etc.), all
    `enabled: false` by default
  - Format follows the standard MCP configuration convention, with an `enabled` field:
      ```json
      {
        "mcpServers": {
          "filesystem": {
            "enabled": false,
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/docs"],
            "env": {},
            "timeout": 30000
          }
        }
      }
      ```
  - `enabled` field: `true` = connect on startup, `false` = skip. Defaults to `true` if omitted (backward compatibility)
  - On startup, bot reads this file and auto-connects to all servers with `enabled: true`
  - **Hot-reload**: A background task polls `mcp.json` every 30 seconds. Changes to the file (enable/disable servers,
    modify config) take effect automatically without restart
  - Hot-reload detects three types of changes: newly enabled servers → connect; disabled/removed servers → disconnect;
    config changed for existing server → reconnect
  - To enable/disable a pre-configured server, edit the `enabled` field in `mcp.json` directly — the hot-reload loop
    handles the rest
    - Config file is optional — if missing or empty, bot starts normally with no MCP servers
- **Error handling**:
    - Invalid JSON → log warning, skip MCP entirely
    - Individual server connection failure → skip that server, continue with others
  - Hot-reload failure → log error, retry on next interval
- **Edge cases**:
    - Empty `mcpServers` object → no MCP connections, no error
  - Config file created after first startup → detected by hot-reload within 30 seconds
  - Server with empty env values (e.g., `"GITHUB_TOKEN": ""`) → connected but env vars passed as-is; user should fill
    values before enabling

### F-02 MCP Server Management Tool (Conversational)

- **Main flow**:
    - New AI tool `mcp_server` for managing **dynamic** MCP servers (not pre-configured ones)
    - Actions: `add`, `remove`, `list`, `list_tools`
    - `add(name, command, args?, env?, timeout?)` → connect to the server, discover tools, persist config
    - `remove(name)` → disconnect session, remove from persisted config
    - `list()` → show all connected servers with status and tool count
    - `list_tools(name?)` → show tools provided by a specific server or all servers
    - Server configs added via chat are persisted to a JSON file (`data/mcp_servers.json`) so they survive restarts
    - On startup, reconnect to both static (`config/mcp.json`) and dynamic (`data/mcp_servers.json`) servers
    - **Separation of concerns**: Pre-configured servers (mcp.json) are managed by editing the config file directly (
      F-01 hot-reload handles the rest). This tool only manages dynamically added servers
- **Error handling**:
    - Connection failure on add → return error to AI, do not persist
    - Server name conflict (same name in static and dynamic) → dynamic takes precedence, log warning
- **Edge cases**:
    - User adds a server that's already in static config → treat as override (dynamic wins)
    - Remove a static server → only disconnects for this session, re-appears on restart (static config unchanged)
    - Remove a dynamic server → permanently removed from `data/mcp_servers.json`

### F-03 MCP Client Connection Manager

- **Main flow**:
    - New module `apps/bot/mcp/client.py` — manages MCP ClientSession lifecycle
    - For each server: spawn the process via stdio, create ClientSession, call `session.initialize()`, then
      `session.list_tools()` to discover tools
    - Maintain a registry of active sessions: `{server_name: {session, tools, config}}`
    - Provide methods: `connect(name, config)`, `disconnect(name)`, `get_all_tools()`, `call_tool(tool_name, arguments)`
    - All MCP sessions cleaned up on bot shutdown
- **Error handling**:
    - Connection timeout → configurable per server (default 30s)
    - Session crash mid-conversation → log error, return error string to AI, mark server as disconnected
    - Process spawn failure → return clear error (e.g., "npx not found")
- **Edge cases**:
    - Server provides a tool with the same name as a native tool → prefix with `mcp_{server}_` to avoid collision
    - Server provides zero tools → connected but effectively inactive, log info

### F-04 MCP Tools Integration with AI

- **Main flow**:
    - MCP tools are formatted identically to native tools (same `to_openai()` / `to_anthropic()` structure)
    - Merged into the provider's tool list alongside native tools
    - AI sees one unified tool list — cannot distinguish MCP from native
    - When AI calls an MCP tool, core routes to `mcp_manager.call_tool(name, args)` instead of `tool.execute()`
    - Tool results returned as strings, same as native tools
    - MCP tools get their own `usage_hint` entries in the system prompt (auto-generated from tool descriptions)
- **Error handling**:
    - MCP tool call fails → return error string to AI (same pattern as native tool failure)
    - MCP server disconnected mid-call → return "Server disconnected" error
- **Edge cases**:
    - MCP tools can change if servers are added/removed mid-session → provider's tool list is rebuilt
    - Tool list rebuild requires updating `provider.tools` — acceptable since it's just reassigning a list

## 4. Non-functional Requirements

- **New dependency**: `mcp` (official Python SDK, `pip install mcp`). This is the only new external package.
- **Architecture consistency**:
    - MCP client manager lives in `apps/bot/mcp/client.py` — a new layer alongside memory/tool/job
    - MCP management tool follows `tool/mcp_server/handler.py` pattern
    - Core orchestrates: creates MCP manager, injects into tool, merges MCP tools with native tools
    - Dependency direction: `mcp/` imports nothing from core/channel/provider/tool/job
- **Performance**: MCP server connections are established at startup, not per-request. Tool calls go through stdio
  pipes (fast for local processes).
- **Data safety**: `data/mcp_servers.json` is under the `.gitignore`-ed data directory. Environment variables in MCP
  configs may contain secrets — they are persisted but the data directory is excluded from git.

## 5. Out of Scope

- MCP Server mode (exposing Synapulse as an MCP server)
- SSE / Streamable HTTP transport (stdio only for v1)
- MCP Resources and Prompts (Tools only)
- MCP sampling (letting MCP servers call back to the AI)
- ~~Hot-reload of static config file~~ (implemented in v2, see F-01)
- Web UI for MCP management

## 6. Acceptance Criteria

| ID    | Feature | Condition                                                    | Expected Result                                                       |
|:------|:--------|:-------------------------------------------------------------|:----------------------------------------------------------------------|
| AC-01 | F-01    | Configure a filesystem MCP server in `mcp.json`, start bot   | Bot logs show MCP connection success and discovered tools             |
| AC-02 | F-01    | Configure an invalid MCP server in `mcp.json`, start bot     | Bot starts normally, logs warning for failed connection               |
| AC-03 | F-02    | User says "connect a GitHub MCP server" in Discord           | AI calls mcp_server.add, connects, reports discovered tools           |
| AC-04 | F-02    | User says "what MCP servers do I have?"                      | AI lists all connected servers with tool counts                       |
| AC-05 | F-02    | User says "disconnect the filesystem server"                 | AI removes the server, MCP tools from that server no longer available |
| AC-06 | F-02    | Restart bot after adding a server via chat                   | Server auto-reconnects from persisted config                          |
| AC-07 | F-03    | MCP server crashes during a conversation                     | AI receives error message, other tools still work                     |
| AC-08 | F-04    | AI asked a question that requires an MCP tool                | AI calls the MCP tool, gets result, answers the user                  |
| AC-09 | F-04    | Both native tool and MCP tool are relevant                   | AI can call either or both in the same conversation                   |
| AC-10 | F-01    | Edit mcp.json to set `enabled: true` for a server            | Hot-reload connects the server within 30 seconds                      |
| AC-11 | F-01    | Edit mcp.json to set `enabled: false` for a connected server | Hot-reload disconnects the server within 30 seconds                   |
| AC-12 | F-01    | Change a server's command/args in mcp.json while running     | Hot-reload reconnects the server with new config                      |

## 7. Change Log

| Version | Date       | Changes                                                                                                          | Affected Scope                   | Reason                                                                                   |
|:--------|:-----------|:-----------------------------------------------------------------------------------------------------------------|:---------------------------------|:-----------------------------------------------------------------------------------------|
| v1      | 2026-03-10 | Initial version                                                                                                  | ALL                              | -                                                                                        |
| v2      | 2026-03-10 | Add `enabled` field, hot-reload, 55 pre-configured servers; clarify mcp_server tool only manages dynamic servers | F-01, F-02, Section 5, Section 6 | Separation of concerns: config file editing for static servers, tool for dynamic servers |
