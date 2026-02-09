---
name: bot-philosophy
description: Design philosophy for the Synapulse bot. These are the guiding principles behind every architectural decision.
disable-model-invocation: false
user-invocable: false
---

# Design Philosophy

These principles guide every decision in `apps/bot/`. They are non-negotiable.

## 1. Plan Before Code

Before implementing a non-trivial feature, **discuss the design first**:

- Clarify requirements and edge cases with the user
- Propose architecture and ask questions before writing code
- Identify which layers are affected and how dependencies flow
- Only start coding after alignment on the approach

## 2. High Cohesion, Low Coupling

Each layer has exactly one job. Peer layers never import each other:

- **core/** — Orchestration. The brain.
- **channel/** — Platform I/O. Passive.
- **provider/** — AI API adapter. Passive.
- **tool/** — Capabilities. Passive.
- **config/** — Static settings and prompts. Shared.

## 3. Core Orchestrates Everything

Core is the sole orchestrator. It controls the entire lifecycle: loading, wiring, and the runtime loop. Other layers are
passive — they expose methods but never initiate cross-layer communication.

This is **inversion of control**: core injects callbacks into channel, sets tool definitions on provider, and drives the
tool-call loop. Channel, provider, and tool never reach out to each other or back to core.

## 4. Self-Validating Implementations

Each implementation validates its own config. Config class only loads and displays values — it has zero knowledge of
which fields belong to which implementation.

Adding a new provider/channel/tool that needs a new env var requires **zero changes** to `config/settings.py`. The new
implementation handles its own validation in `authenticate()`, `validate()`, or similar lifecycle methods.

No central if-else. No match-case. Ever.

## 5. Convention Over Configuration

Dynamic loading via `importlib`. Class names are convention:

- Provider exports `Provider`
- Channel exports `Channel`
- Tool exports `Tool`

No factory, no registry, no mapping dict. Add a folder with the right class name — core finds it automatically.

## 6. Symmetric Base Class Hierarchies

Different API formats are handled through parallel hierarchies:

- **Provider side**: `BaseProvider` → `OpenAIProvider` / `AnthropicProvider` (message formatting)
- **Tool side**: `BaseTool` → `OpenAITool` / `AnthropicTool` (tool definition formatting)

A tool can inherit from multiple format mixins to support multiple APIs. Core reads `provider.api_format`, then calls
`tool.to_{format}()` to bridge the two.

## 7. Guard Clause Style

Prefer positive `if` → do work → return. Errors and exceptions go at the bottom. The happy path reads top-down.

```python
# Good
if config.GITHUB_TOKEN:
    _token = config.GITHUB_TOKEN
    return _token

if config.GITHUB_CLIENT_ID:
    token = _device_flow(config.GITHUB_CLIENT_ID)
    _save_to_env(token)
    _token = token
    return _token

raise RuntimeError("No auth method available")
```

## 8. Single Entry Point

Only `main.py` has `if __name__ == "__main__"`. No other module should have it. Every other module is imported and
called — never run directly.

## 9. No Empty `__init__.py`

Only create `__init__.py` when package-level initialization is genuinely needed. Empty init files are noise.

## 10. Preserve Existing Logic

Never accidentally delete or overwrite working code. When modifying a file, understand what exists first, then make
targeted changes. Lost logic is expensive.
