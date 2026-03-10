# REQ-006 Technical Design

> Status: Technical Finalized
> Requirement: requirement.md
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Technology Stack

| Module         | Technology           | Rationale                                                                   |
|:---------------|:---------------------|:----------------------------------------------------------------------------|
| Config loading | PyYAML + os.environ  | YAML for structured multi-endpoint config, env var expansion for secrets    |
| HTTP client    | aiohttp (existing)   | Already used by copilot/ollama providers, no new dependency                 |
| Concurrency    | asyncio.Lock         | Protect rotation cursor and cooldown state from concurrent mention handlers |
| Hot-reload     | asyncio polling loop | Proven pattern — same as existing MCP config hot-reload in handler.py       |

## 2. Design Principles

- **High cohesion, low coupling**: Rotation logic is self-contained in EndpointPool. Provider only calls pool to get the
  next endpoint — doesn't know about YAML or hot-reload.
- **Reuse first**: Extract the duplicated HTTP chat logic from copilot/ollama into a shared `_http_chat()` method in the
  OpenAI base class. Delete the now-redundant provider directories.
- **Testability**: EndpointPool is a pure in-memory data structure — no I/O, no provider dependency. Rotation, cooldown,
  and filtering can be unit tested independently.
- **Backward compatibility**: `chat()` signature adds only optional parameters. mention.py requires zero changes.

## 3. Architecture Overview

See `tech-architecture.puml`.

The core change is replacing the "one provider directory per endpoint" model with a "YAML config → EndpointPool → base
class rotation" model:

```
Before:  handler.py → importlib → copilot/chat.py (hardcoded URL + auth)
                                   ollama/chat.py  (hardcoded URL + no auth)

After:   handler.py → models.yaml → EndpointPool → OpenAIProvider._http_chat()
                                                     (URL, key, model from pool)
```

Provider class hierarchy remains unchanged:

- `BaseProvider` (abstract contract)
- `OpenAIProvider(BaseProvider)` — format + rotation + HTTP
- `AnthropicProvider(BaseProvider)` — format + rotation + HTTP (future)
- `mock/chat.py::Provider(OpenAIProvider)` — overrides chat() for testing

## 4. Module Design

### 4.1 config/models.py — YAML Config Loader

- **Responsibility**: Load `models.yaml`, validate schema, expand `${ENV_VAR}` references, return typed endpoint list.
- **Public interface**:
  ```python
  @dataclass
  class EndpointConfig:
      name: str
      protocol: str          # "openai" or "anthropic"
      base_url: str
      api_key: str           # after env var expansion, may be empty
      model: str
      tags: list[str]
      enabled: bool = True
      priority: int = 0

  def load_models_config(path: str) -> list[EndpointConfig]:
      """Load and validate models.yaml. Raises ConfigError on invalid format."""

  def build_legacy_endpoint(provider: str, model: str) -> list[EndpointConfig]:
      """Build a single-endpoint config from legacy AI_PROVIDER + AI_MODEL .env settings."""
  ```
- **Internal structure**:
    - `_expand_env_vars(value: str) -> str` — replace `${VAR}` with `os.environ.get(VAR, "")`, warn if missing
    - `_validate_endpoint(raw: dict, index: int) -> EndpointConfig` — check required fields, type coercion
    - Schema validation: `name`, `protocol`, `base_url`, `model`, `tags` are required; `protocol` must be `openai` or
      `anthropic`; `tags` must be non-empty list; `name` must be unique across all endpoints
- **Reuse notes**: `EndpointConfig` dataclass is used by EndpointPool (4.2) and handler.py (4.5).
- **Backward compat (F-08)**: `build_legacy_endpoint()` maps old config to new format:
    - `copilot` →
      `EndpointConfig(protocol="openai", base_url="https://models.inference.ai.azure.com", api_key=GITHUB_TOKEN, ...)`
    - `ollama` → `EndpointConfig(protocol="openai", base_url=OLLAMA_BASE_URL+"/v1", api_key="", ...)`
    - `mock` → returns empty list (mock provider handles itself)
    - Legacy endpoints get `tags=["default"]`

### 4.2 provider/endpoint.py — EndpointPool (Rotation + Cooldown)

- **Responsibility**: Manage a pool of endpoints. Filter by tag, rotate on failure, track cooldowns. Thread-safe.
- **Public interface**:
  ```python
  class EndpointPool:
      def __init__(self, endpoints: list[EndpointConfig]) -> None: ...

      def get_available(self, tag: str) -> list[EndpointConfig]:
          """Return enabled, non-cooldown endpoints matching tag, sorted by priority,
          starting from current cursor position for round-robin."""

      def mark_cooldown(self, name: str, seconds: float) -> None:
          """Mark an endpoint as rate-limited for `seconds`."""

      def advance_cursor(self, tag: str) -> None:
          """Move cursor to next position for the given tag."""

      def update(self, endpoints: list[EndpointConfig]) -> None:
          """Hot-reload: replace endpoint list, preserve cooldown state for
          endpoints that still exist by name."""

      @property
      def endpoint_count(self) -> int: ...

      def get_tag_summary(self) -> dict[str, int]:
          """Return {tag: count_of_enabled_endpoints} for logging."""
  ```
- **Internal structure**:
    - `_endpoints: list[EndpointConfig]` — all configured endpoints
    - `_cursors: dict[str, int]` — per-tag round-robin cursor position
    - `_cooldowns: dict[str, float]` — `{endpoint_name: cooldown_until_timestamp}`
    - `_lock: asyncio.Lock` — protect concurrent access
    - Cooldown check: `time.monotonic() < _cooldowns.get(name, 0)`
    - Cursor wraps around: `cursor % len(filtered_endpoints)`
- **Reuse notes**: Pure data structure with no dependencies on provider or config modules. Can be used by both
  OpenAIProvider and AnthropicProvider.

### 4.3 provider/errors.py — Custom Exceptions

- **Responsibility**: Define exceptions for the rotation layer to distinguish error types.
- **Public interface**:
  ```python
  class RateLimitError(Exception):
      """Raised when an endpoint returns HTTP 429."""
      def __init__(self, retry_after: float = 60.0, message: str = ""):
          self.retry_after = retry_after
          super().__init__(message or f"Rate limited, retry after {retry_after}s")

  class EndpointError(Exception):
      """Raised when an endpoint returns a non-success, non-429 response."""
      def __init__(self, status: int, message: str = ""):
          self.status = status
          super().__init__(message or f"Endpoint error: HTTP {status}")
  ```

### 4.4 provider/base.py — Refactored Base Classes

- **Responsibility**: Add rotation-aware `chat()` and shared `_http_chat()` to format base classes. All existing format
  methods (build_messages, append_tool_result, parse_tool_calls, compress_tool_results) remain unchanged.
- **Key changes to OpenAIProvider**:
  ```python
  class OpenAIProvider(BaseProvider):
      # ... existing format methods unchanged ...

      _pool: EndpointPool | None = None
      _default_tag: str = "default"

      async def chat(self, messages: list, tool_choice: str | None = None,
                     tag: str | None = None) -> ChatResponse:
          """Send messages to AI with automatic endpoint rotation.

          tag: which endpoint group to use (default: self._default_tag).
          Rotation is transparent — caller doesn't need to know about endpoints.
          """
          # If no pool (mock or legacy single-endpoint), subclass overrides this
          effective_tag = tag or self._default_tag
          endpoints = self._pool.get_available(effective_tag)
          if not endpoints:
              return ChatResponse(text=f"[AI Error] No available endpoints for tag '{effective_tag}'")

          last_error = None
          for endpoint in endpoints:
              try:
                  response = await self._http_chat(endpoint, messages, tool_choice)
                  return response
              except RateLimitError as e:
                  logger.warning("Endpoint '%s' rate limited (cooldown %ds), trying next",
                                 endpoint.name, e.retry_after)
                  self._pool.mark_cooldown(endpoint.name, e.retry_after)
                  last_error = e
              except EndpointError as e:
                  logger.warning("Endpoint '%s' error (HTTP %d), trying next",
                                 endpoint.name, e.status)
                  last_error = e
              except Exception as e:
                  logger.warning("Endpoint '%s' unexpected error: %s, trying next",
                                 endpoint.name, e)
                  last_error = e

          self._pool.advance_cursor(effective_tag)
          return ChatResponse(text=f"[AI Error] All endpoints failed: {last_error}")

      async def _http_chat(self, endpoint: EndpointConfig, messages: list,
                           tool_choice: str | None) -> ChatResponse:
          """Execute a single HTTP chat request to one endpoint.
          Raises RateLimitError on 429, EndpointError on other non-200 status."""
          headers = {"Content-Type": "application/json"}
          if endpoint.api_key:
              headers["Authorization"] = f"Bearer {endpoint.api_key}"

          payload = {"model": endpoint.model, "messages": messages}
          if self.tools:
              payload["tools"] = self.tools
              if tool_choice:
                  payload["tool_choice"] = tool_choice

          url = endpoint.base_url.rstrip("/") + "/chat/completions"
          logger.debug("Chat request → %s (model=%s)", endpoint.name, endpoint.model)

          async with aiohttp.ClientSession() as session:
              async with session.post(url, headers=headers, json=payload) as resp:
                  if resp.status == 429:
                      retry_after = float(resp.headers.get("Retry-After", "60"))
                      raise RateLimitError(retry_after=retry_after)
                  if resp.status != 200:
                      text = await resp.text()
                      raise EndpointError(resp.status, text[:200])
                  data = await resp.json()

          msg = data["choices"][0]["message"]
          messages.append(msg)

          tool_calls = self.parse_tool_calls(msg)
          if tool_calls:
              return ChatResponse(tool_calls=tool_calls)

          text = msg.get("content") or "..."
          return ChatResponse(text=text)
  ```
- **AnthropicProvider**: Same pattern — add `chat()` with rotation + `_http_chat()` for Anthropic API format. Deferred
  until an Anthropic endpoint is actually needed.
- **Backward compatibility**: `chat()` signature is `chat(messages, tool_choice=None, tag=None)` — all new params are
  optional. Existing callers (`mention.py`) pass only `messages` and it works.

### 4.5 core/handler.py — Modified Bootstrap & Hot-Reload

- **Responsibility**: Load models.yaml (or legacy config), build EndpointPool, inject into provider, run hot-reload
  loop.
- **Key changes**:
  ```python
  # New: config file paths
  _MODELS_CONFIG = Path(__file__).resolve().parent.parent / "config" / "models.yaml"

  # New: hot-reload interval (reuse MCP pattern)
  _MODELS_RELOAD_INTERVAL = 30

  async def start() -> None:
      # ... existing db init ...

      # NEW: Load model config
      if _MODELS_CONFIG.exists():
          endpoints = load_models_config(str(_MODELS_CONFIG))
          logger.info("Loaded %d model endpoints from models.yaml", len(endpoints))
      else:
          endpoints = build_legacy_endpoint(config.AI_PROVIDER, config.AI_MODEL)
          logger.info("No models.yaml found, using legacy config: %s/%s",
                      config.AI_PROVIDER, config.AI_MODEL)

      # NEW: Build pool and provider
      pool = EndpointPool(endpoints)
      # Determine protocol from endpoints (all must be same protocol for one provider)
      # If mixed protocols needed in future, create separate providers per protocol
      protocol = endpoints[0].protocol if endpoints else "openai"
      if protocol == "openai":
          provider = OpenAIProvider()
      elif protocol == "anthropic":
          provider = AnthropicProvider()

      if endpoints:
          provider._pool = pool
          provider._default_tag = "default"  # or configurable

      # REMOVED: importlib dynamic provider loading
      # REMOVED: provider.authenticate() — no longer needed, api_key is in YAML
      # KEPT: mock provider special case (if no endpoints, fall back to mock)
  ```
- **Hot-reload loop** (follows MCP pattern):
  ```python
  async def _models_reload_loop(pool: EndpointPool, config_path: str) -> None:
      """Background task: periodically re-read models.yaml and update pool."""
      last_mtime = _get_mtime(config_path)
      while True:
          await asyncio.sleep(_MODELS_RELOAD_INTERVAL)
          try:
              current_mtime = _get_mtime(config_path)
              if current_mtime == last_mtime:
                  continue
              last_mtime = current_mtime

              new_endpoints = load_models_config(config_path)
              pool.update(new_endpoints)
              logger.info("Models config reloaded: %d endpoints, tags: %s",
                          pool.endpoint_count, pool.get_tag_summary())
          except FileNotFoundError:
              logger.warning("models.yaml deleted, keeping current config")
          except Exception:
              logger.exception("Models config reload failed, keeping current config")
  ```
- **Removed**: `importlib.import_module(f"apps.bot.provider.{config.AI_PROVIDER}.chat")` — no longer needed.
- **Kept**: Mock provider fallback — if `AI_PROVIDER=mock` and no YAML, import mock directly.

### 4.6 Cleanup — Removed Provider Directories

- **copilot/chat.py**: DELETED. The HTTP logic moves to `OpenAIProvider._http_chat()`. The `base_url` and `api_key` come
  from YAML config.
- **ollama/chat.py**: DELETED. Same reason — identical to copilot except for URL and no auth.
- **copilot/auth.py**: KEPT as standalone utility. Users can run it to populate `GITHUB_TOKEN` in `.env`, which is then
  referenced as `${GITHUB_TOKEN}` in models.yaml.
- **mock/chat.py**: KEPT. Overrides `chat()` to return fixed response. Used for testing.

### 4.7 models.yaml Configuration Schema

```yaml
# apps/bot/config/models.yaml
models:
  - name: github-gpt4o
    protocol: openai
    base_url: https://models.inference.ai.azure.com
    api_key: ${GITHUB_TOKEN}
    model: gpt-4o
    tags: [ large, default ]
    enabled: true
    priority: 0

  - name: ollama-llama70b
    protocol: openai
    base_url: http://localhost:11434/v1
    model: llama3.1:70b
    tags: [ large ]
    enabled: true
    priority: 10

  - name: github-gpt4o-mini
    protocol: openai
    base_url: https://models.inference.ai.azure.com
    api_key: ${GITHUB_TOKEN}
    model: gpt-4o-mini
    tags: [ small, default ]
    enabled: true
    priority: 0
```

**Field reference:**

| Field    | Type      | Required | Default | Description                                   |
|:---------|:----------|:---------|:--------|:----------------------------------------------|
| name     | string    | Yes      | -       | Unique endpoint identifier                    |
| protocol | string    | Yes      | -       | `openai` or `anthropic`                       |
| base_url | string    | Yes      | -       | API base URL (without `/chat/completions`)    |
| api_key  | string    | No       | `""`    | API key, supports `${ENV_VAR}`                |
| model    | string    | Yes      | -       | Model name sent in API payload                |
| tags     | list[str] | Yes      | -       | At least one tag for filtering                |
| enabled  | bool      | No       | `true`  | Hot-reloadable on/off switch                  |
| priority | int       | No       | `0`     | Lower = higher priority within same tag group |

## 5. Data Model

See `tech-class.puml`.

No database changes. All state is in-memory:

```
EndpointConfig (dataclass, immutable)
├── name: str
├── protocol: str
├── base_url: str
├── api_key: str
├── model: str
├── tags: list[str]
├── enabled: bool
└── priority: int

EndpointPool (mutable, thread-safe)
├── _endpoints: list[EndpointConfig]
├── _cursors: dict[str, int]        # {tag: cursor_position}
├── _cooldowns: dict[str, float]    # {endpoint_name: cooldown_until}
└── _lock: asyncio.Lock
```

## 6. API Design

No external API changes. The `chat()` method signature change is internal:

```python
# Before
async def chat(self, messages: list, tool_choice: str | None = None) -> ChatResponse


# After (backward compatible — new params are optional)
async def chat(self, messages: list, tool_choice: str | None = None, tag: str | None = None) -> ChatResponse
```

## 7. Key Flows

See `tech-sequence.puml`.

### 7.1 Startup Flow

1. Check if `config/models.yaml` exists
2. If yes → `load_models_config()` → parse, validate, expand env vars → `list[EndpointConfig]`
3. If no → `build_legacy_endpoint()` → single endpoint from `.env` config
4. Create `EndpointPool(endpoints)`
5. Create provider (OpenAI or Anthropic based on protocol)
6. Inject pool into provider: `provider._pool = pool`
7. Start `_models_reload_loop()` background task

### 7.2 Chat Request Flow (with rotation)

1. `mention.py` calls `provider.chat(messages)` (no tag → uses `_default_tag`)
2. `chat()` calls `self._pool.get_available(tag)` → sorted, filtered list
3. For each endpoint in list:
   a. Call `_http_chat(endpoint, messages, tool_choice)`
   b. On success → return ChatResponse
   c. On 429 → `pool.mark_cooldown(name, retry_after)` → try next
   d. On other error → log warning → try next
4. All failed → `pool.advance_cursor(tag)` → return error ChatResponse

### 7.3 Hot-Reload Flow

1. Every 30s, check `models.yaml` mtime
2. If changed → `load_models_config()` → `pool.update(new_endpoints)`
3. `update()` preserves cooldown state for endpoints that still exist by name
4. New endpoints are immediately available; removed endpoints are dropped
5. If reload fails (YAML error) → keep current config, log ERROR

## 8. Shared Modules & Reuse Strategy

| Shared Component           | Used By                                       | Description                                                                                            |
|:---------------------------|:----------------------------------------------|:-------------------------------------------------------------------------------------------------------|
| `EndpointConfig` dataclass | models.py, endpoint.py, base.py               | Single source of truth for endpoint definition                                                         |
| `EndpointPool` class       | OpenAIProvider, AnthropicProvider, handler.py | Protocol-agnostic rotation + cooldown logic                                                            |
| `_http_chat()` pattern     | OpenAIProvider, AnthropicProvider (future)    | Each protocol base class has its own _http_chat, but the rotation wrapper in chat() is identical logic |
| Hot-reload loop pattern    | handler.py (MCP reload + models reload)       | Same mtime-check-and-reload pattern                                                                    |
| `_expand_env_vars()`       | models.py                                     | Could be reused for any future YAML config with secrets                                                |

## 9. Risks & Notes

1. **Migration**: Existing users with `AI_PROVIDER=copilot` in `.env` and no `models.yaml` will use the backward compat
   fallback (F-08). This is seamless — no action required from users.

2. **copilot/auth.py preservation**: OAuth Device Flow is kept as a standalone utility. Users who need it can run it to
   populate `GITHUB_TOKEN` in `.env`. The auth module is NOT deleted.

3. **Mixed protocols**: If `models.yaml` contains both `openai` and `anthropic` endpoints, the system currently creates
   one provider instance. A single provider cannot mix protocols (message formats differ). **Current scope: all
   endpoints must share the same protocol.** Mixed protocol support is a future enhancement (would require separate
   provider instances per protocol).

4. **Concurrency safety**: Multiple Discord mentions can arrive simultaneously. `EndpointPool` uses `asyncio.Lock` to
   protect cursor and cooldown mutations. The lock is held only for in-memory dict/list operations (microseconds), so
   contention is negligible.

5. **aiohttp session management**: Currently each `_http_chat()` call creates a new `aiohttp.ClientSession`. For higher
   throughput, a shared session could be used. Deferred to future optimization — current personal-use volume doesn't
   warrant it.

6. **Cooldown accuracy**: `Retry-After` may be seconds or an HTTP-date. First version only handles numeric seconds.
   HTTP-date parsing is a future enhancement.

## 10. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version | ALL            | -      |
