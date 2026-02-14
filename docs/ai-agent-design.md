# AI Agent Design — Lessons from Building a Personal Assistant

Practical lessons learned from building Synapulse's AI core. These apply to any project that
uses LLMs as tool-calling agents rather than simple chatbots.

## The Core Challenge

Moving from **probabilistic generation** to **deterministic execution**. A chatbot can hallucinate
and it's annoying; an agent that hallucinate tool calls wastes money and breaks workflows.

The fix is never "better prompts" alone — it's **architectural constraints** that leave the model
no room to go wrong.

---

## Problem 1: Ensuring Tool Calls and Parameters

**Goal:** AI must call the right tool with correct arguments.

### What works

| Layer      | Mechanism                                                                                                                                                                                                         |
|------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| API        | `tool_choice` parameter — forces the model to emit a tool call instead of text. Use `"required"` to guarantee *some* tool call, or `{"name": "X"}` to force a *specific* tool. Default `"auto"` for general chat. |
| Schema     | Strict JSON Schema in tool definitions. Use `enum` for constrained values, `required` for mandatory fields. The tighter the schema, the less room for hallucination.                                              |
| Validation | Validate arguments **before** execution (e.g. `jsonschema.validate()`). If invalid, return a structured error message to the AI — not a crash.                                                                    |
| Prompt     | 3-5 few-shot examples of correct tool calls in the system prompt. Critical for complex parameter logic.                                                                                                           |

### What doesn't work

- Relying solely on natural language instructions ("please call tool X when...")
- Trusting the model to always produce valid JSON on first try
- Using Pydantic models for 2-3 simple tools (over-engineering)

### Synapulse decision

- Tools define `parameters` as JSON Schema — already strict enough
- `tool_choice` parameter reserved on `provider.chat()` interface, default `"auto"`
- Pre-execution validation via `jsonschema.validate()` in the tool-call loop — invalid arguments
  never reach `tool.execute()`, the AI gets a structured error and retries on the next round
- Error strings flow back to AI naturally through the existing loop

---

## Problem 2: Flow Completeness and Exit Mechanisms

**Goal:** Multi-step tasks (scan a directory tree, search + read + summarize) must complete
reliably and stop cleanly.

### Two strategies

**Strategy A: Code does the loop (preferred for mechanical tasks)**

Don't let the AI decide "scan next directory." Give it a tool like `list_files_recursive` that
handles traversal internally and returns a complete result. The AI only needs one call.

Best for: file search, log aggregation, batch operations.

**Strategy B: AI-driven loop with guardrails (for decision-heavy tasks)**

Let the AI iterate, but constrain it:

| Guardrail                      | Purpose                                                                                           |
|--------------------------------|---------------------------------------------------------------------------------------------------|
| `MAX_TOOL_ROUNDS` (hard limit) | Prevents infinite loops. Set to 10-15 depending on task complexity.                               |
| Tool-side caps                 | `MAX_LIST_ENTRIES = 100`, `MAX_READ_CHARS = 10000` — truncate large outputs at the source.        |
| Implicit termination signals   | `(empty directory)`, `No results found.` — the AI learns to stop.                                 |
| Explicit termination           | System prompt instructs: "When done, provide your final answer. Do not call tools unnecessarily." |

### Synapulse decision

- `local_files` uses Strategy B — one level at a time, AI decides where to drill down
- `brave_search` uses Strategy A — one call returns up to 5 results
- Hard limit: 10 rounds with 1s pause between rounds (rate-limit protection)
- Tool-side caps prevent individual results from exploding

### What to watch for

- AI re-listing the same directory (wasted round) — improve prompt guidance
- AI reading every file instead of picking relevant ones — improve tool description
- Hitting max rounds on legitimate deep tasks — consider raising limit per-tool

---

## Problem 3: Action Routing After Instructions

**Goal:** Given a user message, the AI should pick the right tool (or no tool) reliably.

### Spectrum of approaches

```
Simple ←──────────────────────────────────→ Complex

Tool descriptions    System prompt      Classification    Planner-Executor
only (let model      with routing       step (cheap       (planning model +
figure it out)       hints              model routes)     execution model)
```

### When to use what

| Approach               | When                                              |
|------------------------|---------------------------------------------------|
| Tool descriptions only | 1-3 tools, clear domains, no overlap              |
| System prompt routing  | 3-10 tools, some overlap, need disambiguation     |
| Classification step    | 10+ tools, or when wrong tool choice is expensive |
| Planner-Executor       | Complex multi-step tasks with branching logic     |

### Synapulse decision

- Currently: system prompt routing (hardcoded tool hints in `prompts.py`)
- Planned improvement: auto-generate the Tools section from `tool.usage_hint` attributes
- No planner needed — a personal assistant with 2-3 tools doesn't justify the overhead

### Anti-pattern

Hardcoding tool routing in the system prompt while using dynamic tool loading. Every new tool
requires a manual prompt edit — this defeats the purpose of `scan_tools()`. Let each tool carry
its own routing hint, and have the loader assemble them at startup.

### Synapulse implementation

Each tool has a `usage_hint` class attribute (falls back to `description` if empty).
At startup, `core/loader.format_tool_hints()` builds per-tool lines, and
`core/mention.make_mention_handler()` assembles the full system prompt once:
`SYSTEM_PROMPT + "## Tools\n" + TOOLS_GUIDANCE + per-tool hints`. Adding a new tool requires
zero changes to the prompt — just set `usage_hint` on the Tool class.

---

## Problem 4: Token Management in Multi-Round Loops

**Goal:** Keep context lean across many tool-call rounds. Token cost grows linearly with
rounds if unchecked.

### The problem visualized

```
Round 1: system + user + assistant(tool_call) + tool_result(5KB)
Round 2: all of round 1 + assistant(tool_call) + tool_result(8KB)
Round 3: all of round 1-2 + assistant(tool_call) + tool_result(3KB)
...
Round 5: system + user + 4 assistant messages + 16KB of stale tool results
```

Every round re-sends ALL previous tool results. A 5-round file browsing session can hit
30-50K tokens of accumulated tool output that the AI has already processed.

### Solutions (ordered by complexity)

| Strategy                  | How                                                                                                                     | Complexity |
|---------------------------|-------------------------------------------------------------------------------------------------------------------------|------------|
| **Result compression**    | After AI responds to tool results, replace them with `[Compressed: N chars]`. Only the latest round's results are full. | Low        |
| Tool-side truncation      | Cap output at source (`MAX_READ_CHARS`).                                                                                | Low        |
| Sliding window            | Keep only the last N rounds of history. Summarize older rounds.                                                         | Medium     |
| Observation summarization | Use a cheap model (Haiku/4o-mini) to summarize large tool outputs before feeding to the main model.                     | Medium     |
| Diff-mode output          | AI outputs only changed lines, not full files (Cursor's SEARCH/REPLACE blocks).                                         | High       |
| Context pruning           | Dynamically remove irrelevant history based on current task.                                                            | High       |

### Synapulse decision

- **Implemented:** Result compression in `provider.compress_tool_results()` — threshold 200 chars.
  After `provider.chat()` returns (AI has consumed all messages), old tool results are replaced
  with a size note. New results from the current round stay in full for the next round.
- **Implemented:** Tool-side truncation (10K chars for files, 100 entries for directories).
- **Not needed yet:** Sliding window, observation summarization, diff-mode. These are for
  heavier workloads (IDE-scale, not personal assistant-scale).

### The compression flow

```
provider.chat(messages)         ← AI sees everything, responds
provider.compress_tool_results  ← shrink all tool results (AI already consumed them)
tool.execute → append results   ← new results at full fidelity
provider.chat(messages)         ← AI sees compressed old + full new
```

---

## Industrial Practices (Cursor, Claude Code)

What production-grade AI developer tools do differently:

### Schema validation + auto-retry

AI output is treated as a "proposal," not a final result. A validator checks it against the
tool's JSON Schema. If invalid, the error is fed back automatically — invisible to the user.

### Pre-indexing vs. real-time traversal

Cursor uses RAG + LSP to pre-index the entire codebase. When asked "find X," it queries the
index instead of letting the AI scan directories. Claude Code uses recursive agent loops with
strict step limits.

### Diff-mode output

AI never regenerates entire files. It outputs SEARCH/REPLACE blocks — only the changed lines.
This saves 90%+ of output tokens on file edits.

### Prompt caching

Complex tool schemas are cached (Anthropic Prompt Caching), reducing latency and cost for
repeated conversations with the same tool set.

### Context pruning

Irrelevant history is dynamically removed. If you're editing CSS, previous database discussion
is temporarily dropped from context.

### Multi-model strategy

Expensive models (Opus, Sonnet) for reasoning and planning. Cheap models (Haiku, 4o-mini) for
formatting, summarization, and classification.

---

## Summary: The Agent Stability Formula

```
Strict tool schemas          → model can't hallucinate parameters
Pre-execution validation     → catch errors before they reach tools
Error feedback loops         → model self-corrects on next round
Token compression            → multi-round loops stay affordable
Hard round limits            → infinite loops are impossible
Tool-side output caps        → individual results stay manageable
```

The goal is not to make the AI smarter — it's to make the **system** robust enough that the
AI's occasional mistakes are caught, corrected, and contained automatically.
