# REQ-010: Relative Time Support for Reminders

## Status: Draft

## Created: 2026-03-11

## Author: User + Claude

---

## 1. Background & Problem

### Current Situation

The reminder tool only accepts ISO 8601 absolute timestamps (e.g. `2026-03-11T22:50:00`).

When a user says "5分钟后提醒我喝水", the AI must:

1. Call `shell_exec` to run `date` and learn the current time
2. Mentally calculate current_time + 5 minutes
3. Format as ISO 8601 and call `reminder.create`

This is a **two-step tool chain** that depends on the AI doing time arithmetic correctly — fragile and unreliable.

### Desired Behavior

User says "5分钟后提醒我喝水" → AI calls `reminder.create(remind_at="+5m", message="喝水")` → done in one step. The tool
resolves relative time server-side where the clock is authoritative.

---

## 2. Requirements

### REQ-010-01: Support Relative Time in remind_at

The `remind_at` parameter should accept both:

- **Absolute**: ISO 8601 format (existing, unchanged) — `2026-03-11T22:50:00`
- **Relative**: Shorthand offset from now — `+5m`, `+1h`, `+2h30m`, `+1d`

Supported relative units:
| Suffix | Meaning |
|--------|---------|
| `m`    | minutes |
| `h`    | hours |
| `d`    | days |

Format: `+` prefix followed by one or more `<number><unit>` groups.
Examples: `+5m`, `+1h`, `+2h30m`, `+1d`, `+1d12h`

### REQ-010-02: Update Tool Description & Usage Hint

- Update `description` and `remind_at` parameter description to mention relative time support
- Update `usage_hint` to guide the AI to prefer relative time for "in X minutes/hours" requests
- Update `BEHAVIOR_STRATEGY` in prompts.py if needed

### REQ-010-03: Preserve Existing Behavior

- Absolute ISO 8601 timestamps must continue to work exactly as before
- Recurrence, list, cancel — all unchanged
- Database schema unchanged (relative time is resolved to absolute before storage)
- Background checker unchanged

---

## 3. Scope

### In Scope

| File                                | Change                                                            |
|-------------------------------------|-------------------------------------------------------------------|
| `apps/bot/tool/reminder/handler.py` | Add relative time parsing in `_parse_time()`, update descriptions |
| `apps/bot/config/prompts.py`        | Update reminder guidance in `BEHAVIOR_STRATEGY`                   |

### Out of Scope

- Database changes
- Background checker changes (`core/reminder.py`)
- New tool parameters

---

## 4. Acceptance Criteria

1. `reminder.create(remind_at="+5m", message="test")` creates a reminder 5 minutes from now
2. `+1h`, `+2h30m`, `+1d` all resolve correctly
3. Existing ISO 8601 format still works
4. Invalid relative format returns a clear error message
5. The resolved absolute time is stored in the database (not the relative string)

---

## Change Log

| Version | Date       | Description   |
|---------|------------|---------------|
| 1.0     | 2026-03-11 | Initial draft |
