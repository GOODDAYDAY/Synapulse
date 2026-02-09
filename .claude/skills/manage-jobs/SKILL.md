# Manage Jobs

CRUD operations on `apps/bot/config/jobs.json` — the hot-reloadable config for background jobs.

## JSON Schema

```json
{
  "<job_name>": {
    "enabled": false,
    "schedule": "*/5 * * * *",
    "notify_channel": "",
    "prompt": "..."
  }
}
```

## Fields

| Field            | Type     | Description                                                            |
|------------------|----------|------------------------------------------------------------------------|
| `enabled`        | `bool`   | `true` to run the job, `false` to disable. Default: `false`            |
| `schedule`       | `string` | Cron expression (CronJob only). Overrides the class default            |
| `notify_channel` | `string` | Discord channel ID where notifications are sent. Required when enabled |
| `prompt`         | `string` | System prompt for AI summarization. Overrides the class default        |

## Rules

- Keys must match the `name` attribute of a Job class (e.g. `gmail_monitor`)
- Missing key or `enabled: false` → job sleeps and rechecks every 60 seconds
- Changes take effect on the next tick — no restart required (hot reload)
- Secrets (passwords, tokens) stay in `.env`, NOT in this file
- Keep valid JSON — parse errors disable all jobs until fixed

## Operations

- **Enable a job**: set `"enabled": true` and fill in `notify_channel`
- **Disable a job**: set `"enabled": false`
- **Change schedule**: update `"schedule"` with a valid cron expression
- **Change prompt**: update `"prompt"` with new text
- **Add a new job**: add a new key matching the job's `name` attribute
