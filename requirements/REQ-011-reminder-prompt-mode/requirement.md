# REQ-011: Reminder Prompt Mode

## Status: Completed

## Created: 2026-03-11

## Author: User + Claude

---

## 1. Background & Problem

Current reminders are static text notifications — they echo back the message as-is.
This works for "提醒我喝水" but fails for "告诉我现在时间" or "告诉我今天天气",
where the user expects the bot to **execute** the request, not parrot it back.

## 2. Requirements

### REQ-011-01: Add mode Field to Reminder

- `notify` (default): fire as static text `⏰ Reminder: {message}` (existing behavior)
- `prompt`: fire by feeding message into the AI tool-call loop as if user sent it

### REQ-011-02: AI Selects Mode at Creation Time

- "提醒我喝水" → mode=notify (just a nudge)
- "告诉我现在时间" / "帮我查天气" → mode=prompt (needs AI action)
- AI decides based on whether the message is a passive reminder or an active request

### REQ-011-03: Prompt Mode Execution

When a prompt-mode reminder fires:

1. Take the `message` as user input
2. Run it through the existing AI tool-call loop (`core/mention.py`)
3. Send the AI's response to the reminder's `channel_id`
4. Reuse the entire core flow — no duplicate logic

### REQ-011-04: Inversion of Control

- `core/reminder.py` receives an `on_prompt` callback (injected by `core/handler.py`)
- The callback signature mirrors the mention handler: `(channel_id, message) -> None`
- Reminder checker does NOT import core/mention — it calls the injected callback

### REQ-011-05: Data Persistence

- Add `mode` field to reminder JSON record (default: "notify")
- Backward compatible: existing reminders without `mode` field treated as "notify"

## 3. Scope

| File                                | Change                                          |
|-------------------------------------|-------------------------------------------------|
| `apps/bot/tool/reminder/handler.py` | Add `mode` parameter, update descriptions       |
| `apps/bot/core/reminder.py`         | Handle prompt mode via injected callback        |
| `apps/bot/core/handler.py`          | Inject on_prompt callback into reminder checker |
| `apps/bot/memory/database.py`       | Store `mode` field in reminder record           |

## 4. Acceptance Criteria

1. `reminder.create(remind_at="+5m", message="喝水", mode="notify")` → fires as static text
2. `reminder.create(remind_at="+5m", message="现在几点", mode="prompt")` → fires by AI processing, returns real time
3. Existing reminders (no mode field) continue to work as notify
4. No circular imports — callback injection only

---

## Change Log

| Version | Date       | Description   |
|---------|------------|---------------|
| 1.0     | 2026-03-11 | Initial draft |
