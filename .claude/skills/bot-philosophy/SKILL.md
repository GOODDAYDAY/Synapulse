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
- **job/** — Background tasks. Passive (receives callbacks from core).
- **config/** — Static settings and prompts. Shared.

## 3. Core Orchestrates Everything

Core is the sole orchestrator. It controls the entire lifecycle: loading, wiring, and the runtime loop. Other layers are
passive — they expose methods but never initiate cross-layer communication.

This is **inversion of control**: core injects callbacks into channel and jobs, sets tool definitions on provider, and
drives the tool-call loop. Channel, provider, tool, and job never reach out to each other or back to core.

## 4. Self-Validating Implementations

Each implementation validates its own config in `authenticate()`, `validate()`, or similar lifecycle methods.
Config class loads and displays values — it never decides which fields belong to which implementation.

No central if-else. No match-case. Ever.

## 5. Convention Over Configuration

Dynamic loading via `importlib`. Class names are convention:

- Provider exports `Provider`
- Channel exports `Channel`
- Tool exports `Tool`
- Job exports `Job`

No factory, no registry, no mapping dict. Add a folder with the right class name — core finds it automatically.

## 6. Symmetric Base Class Hierarchies

Different API formats are handled through parallel hierarchies:

- **Provider side**: `BaseProvider` → `OpenAIProvider` / `AnthropicProvider` (message formatting)
- **Tool side**: `BaseTool` → `OpenAITool` / `AnthropicTool` (tool definition formatting)

A tool can inherit from multiple format mixins to support multiple APIs. Core reads `provider.api_format`, then calls
`tool.to_{format}()` to bridge the two.

## 7. Code Does Mechanics, AI Does Decisions

Code handles mechanical tasks: traversal, I/O, formatting. AI handles decisions: matching, relevance, judgment.

Never write code that decides what "matches" a user's intent — that's the AI's job. Code collects data and hands it
over; AI interprets and chooses.

Example: when the user asks "find my resume", code recursively lists the directory tree; AI looks at the results and
decides which entry is the resume.

## 8. Token-Conscious Orchestration

Tool results are consumed once by the AI, then compressed. The core never sends the same large payload twice.

When the AI has responded to a set of tool results (proving it has processed them), those results are replaced with a
brief size note in the message history. This keeps context lean across multi-round tool loops.

Rule: only the **latest round's** tool results are sent in full. Everything older is compressed. The threshold is low
(200 chars) — short results like error messages or "No results found." stay intact because they cost almost nothing.

This is the highest-leverage optimization for token cost in agent loops. A 5-round file browsing session that would
accumulate 30-50K tokens of stale tool results now stays under 5K.

## 9. Guard Clause Style

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

## 10. Single Entry Point

Only `main.py` has `if __name__ == "__main__"`. No other module should have it. Every other module is imported and
called — never run directly.

## 11. No Empty `__init__.py`

Only create `__init__.py` when package-level initialization is genuinely needed. Empty init files are noise.

## 12. Preserve Existing Logic

Never accidentally delete or overwrite working code. When modifying a file, understand what exists first, then make
targeted changes. Lost logic is expensive.
