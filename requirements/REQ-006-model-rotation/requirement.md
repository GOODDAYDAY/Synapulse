# REQ-006 Multi-Model Rotation & Auto-Fallback

> Status: Requirement Finalized
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Background

Synapulse currently operates in a "single provider, single model" mode — `AI_PROVIDER` selects one provider at startup,
`AI_MODEL` selects one model, and both remain fixed for the entire runtime. This causes several problems:

- **No fault tolerance**: When the API is rate-limited or down, the assistant becomes completely unavailable.
- **No elasticity**: Cannot use different models for different scenarios (e.g., cheap model for simple queries, powerful
  model for complex tasks).
- **Rigid configuration**: Adding a new API endpoint requires creating a new provider directory, even though most
  endpoints are OpenAI-compatible.
- **Not scalable**: Cannot leverage multiple free quotas simultaneously (e.g., GitHub Models + Ollama + other
  OpenAI-compatible services).

The solution is a YAML-based multi-endpoint configuration with tag-based filtering, automatic round-robin rotation
within the same protocol, and rate-limit-aware auto-fallback.

## 2. Target Users & Scenarios

- **Primary user**: Bot owner configuring multiple AI endpoints for resilience and flexibility.
- **Scenario 1**: Daily use — tag=`small` model group handles simple questions, saving quota.
- **Scenario 2**: Complex tasks (multi-round tool-call) — tag=`large` model group ensures quality.
- **Scenario 3**: An endpoint triggers 429 rate limit — auto-rotate to the next endpoint in the same group, user is
  unaware.
- **Scenario 4**: Local Ollama is stopped — auto-fallback to cloud endpoint.
- **Scenario 5**: Disable an endpoint via `enabled: false` in YAML — hot-reload picks up the change without restart.

## 3. Functional Requirements

### F-01 YAML Model Configuration

- **Main flow**: New `config/models.yaml` defines multiple model endpoints. Each entry contains:
    - `name` (string, required): Unique identifier (e.g., `github-gpt4o`)
    - `protocol` (string, required): Protocol type (`openai` or `anthropic`), determines message format
    - `base_url` (string, required): API endpoint URL
    - `api_key` (string, optional): API key, supports `${ENV_VAR}` environment variable reference
    - `model` (string, required): Model name
    - `tags` (list of strings, required): Tag list (e.g., `[large, primary]`)
    - `enabled` (boolean, optional): Whether this endpoint is active, defaults to `true`
    - `priority` (integer, optional): Priority within same tag group, lower = higher priority, defaults to 0
- **Error handling**: YAML format error, missing required fields → startup error with clear message
- **Edge cases**: Empty file, no endpoints, duplicate `name` → startup error

### F-02 Tag-Based Endpoint Filtering

- **Main flow**: When making a request, specify a tag (e.g., `large`). The system filters all enabled endpoints that
  contain the tag and match the required protocol.
- **Error handling**: Specified tag has no matching enabled endpoints → return clear error message
- **Edge cases**: A single endpoint can have multiple tags (e.g., `[large, coding]`). Tag queries are single-tag exact
  match — no multi-tag combination queries.

### F-03 Round-Robin Rotation Within Same Protocol

- **Main flow**: Within a filtered set (same tag, same protocol), endpoints are sorted by priority, then rotated on
  failure. Each request failure (rate limit / network error) automatically tries the next endpoint.
- **Rotation strategy**: Maintain a per-tag cursor. On success, cursor stays (prefer same endpoint next time). On
  failure, cursor advances.
- **Error handling**: All endpoints in the group fail → return the last error message to the user.
- **Edge cases**: Single endpoint degrades to direct connection, no rotation overhead.

### F-04 Rate Limit Detection & Auto-Fallback

- **Main flow**: The provider's `chat()` method detects HTTP 429 or provider-specific rate limit signals, raises
  `RateLimitError`. The rotation layer catches it and tries the next endpoint.
- **Backoff**: Rate-limited endpoints are marked with a cooldown period (read from `Retry-After` header, default 60s).
  Skipped during cooldown.
- **Error handling**: Non-rate-limit errors (e.g., 401 auth failure, 500 server error) also trigger fallback, logged as
  WARNING.
- **Edge cases**: All endpoints in cooldown → return error to user (do not block/wait).

### F-05 Environment Variable Expansion in YAML

- **Main flow**: `api_key: ${GITHUB_TOKEN}` is replaced with `os.environ["GITHUB_TOKEN"]` value at load time.
- **Error handling**: Referenced env var does not exist → WARNING log at startup (not fatal, the endpoint is marked as
  unavailable).
- **Edge cases**: Endpoints without `api_key` (e.g., Ollama) can omit the field or set it to empty string.

### F-06 Provider Base Class Refactor

- **Main flow**: Implement rotation logic in `OpenAIProvider` / `AnthropicProvider` base classes. The `chat()` method
  signature remains unchanged; rotation happens internally.
- **Backward compatibility**: `mention.py` requires zero changes — `provider.chat(messages)` call pattern is preserved.
- **Key change**: Provider no longer binds to a single `base_url`/`api_key`/`model`, but holds a group of endpoints and
  rotates among them.

### F-07 Hot-Reload for models.yaml

- **Main flow**: Periodically poll `models.yaml` for changes (similar to existing `mcp.json` hot-reload). When the file
  changes, reload the endpoint list and update the rotation state.
- **Reload behavior**:
    - New endpoints are added to the pool
    - Removed endpoints are dropped from the pool
    - Changed `enabled` field takes effect immediately (e.g., `enabled: false` disables an endpoint without restart)
    - Cooldown states are preserved for endpoints that still exist
- **Error handling**: Reload fails (YAML syntax error) → keep current config, log ERROR
- **Edge cases**: File deleted → keep current config, log WARNING

### F-08 Backward Compatibility Fallback

- **Main flow**: If `models.yaml` does not exist, fall back to the legacy `AI_PROVIDER` + `AI_MODEL` configuration from
  `.env`.
- **Behavior**: Construct a single-endpoint configuration internally, preserving all existing behavior.
- **Edge cases**: Both `models.yaml` and `AI_PROVIDER` are missing → startup error.

## 4. Non-functional Requirements

- **Performance**: Rotation logic is pure in-memory (cursor movement), introduces no additional I/O. Zero impact on
  request latency.
- **Logging**: Each fallback logs INFO (from which endpoint to which). Rate limits log WARNING with cooldown duration.
- **Concurrency**: Rotation cursor and cooldown state must be thread-safe / asyncio-safe (multiple Discord messages may
  trigger mentions concurrently).

## 5. Out of Scope

- ~~Cross-protocol rotation~~ (OpenAI ↔ Anthropic cannot switch mid-conversation due to incompatible message formats)
- ~~Intelligent model routing~~ (auto-select large/small based on query complexity — requires AI pre-analysis, future
  feature)
- ~~OAuth Device Flow in YAML~~ (complex auth flows remain in separate auth modules)
- ~~Cost tracking / token usage statistics~~
- ~~Startup connectivity check~~ (no probe requests at startup; failures are handled at request time)

## 6. Acceptance Criteria

| ID    | Feature | Condition                                                   | Expected Result                                                      |
|:------|:--------|:------------------------------------------------------------|:---------------------------------------------------------------------|
| AC-01 | F-01    | Configure models.yaml with 3 endpoints (2 large, 1 small)   | Startup loads correctly, log shows endpoint count per tag            |
| AC-02 | F-01    | models.yaml has format error (e.g., missing protocol field) | Startup reports clear error                                          |
| AC-03 | F-02    | Request with tag=large                                      | Only selects from large-tagged enabled endpoints                     |
| AC-04 | F-02    | Request with non-existent tag                               | Returns clear error message                                          |
| AC-05 | F-03    | First endpoint returns rate limit                           | Auto-rotates to second endpoint, user gets normal reply              |
| AC-06 | F-03    | All endpoints in a tag group fail                           | Returns error message, no infinite retry                             |
| AC-07 | F-04    | Endpoint returns 429 + Retry-After: 30                      | Endpoint enters 30s cooldown, skipped during that period             |
| AC-08 | F-05    | api_key uses `${GITHUB_TOKEN}`                              | Runtime correctly substitutes environment variable value             |
| AC-09 | F-05    | References non-existent env var                             | WARNING log at startup, does not crash                               |
| AC-10 | F-06    | mention.py code is unchanged                                | `provider.chat()` call works as before, gains rotation automatically |
| AC-11 | F-07    | Change `enabled: false` in models.yaml while running        | Endpoint is excluded from rotation within one reload cycle           |
| AC-12 | F-07    | models.yaml has syntax error during hot-reload              | Current config preserved, ERROR logged                               |
| AC-13 | F-08    | models.yaml does not exist                                  | Falls back to AI_PROVIDER + AI_MODEL legacy config                   |
| AC-14 | F-04    | Non-rate-limit error (500 server error)                     | Triggers fallback, WARNING logged                                    |

## 7. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version | ALL            | -      |
