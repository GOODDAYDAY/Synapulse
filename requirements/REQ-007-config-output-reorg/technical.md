# REQ-007 Technical Design

> Status: Technical Finalized
> Requirement: requirement.md
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Technology Stack

| Module          | Technology       | Rationale                           |
|:----------------|:-----------------|:------------------------------------|
| Path management | Python pathlib   | Already used throughout project     |
| Config loading  | Existing loaders | No new framework, just path updates |

## 2. Design Principles

- Minimal change: only modify path references, no functional logic changes
- Single source of truth: define project root `_root` in settings.py, derive all paths from it
- Backward compatible: DATABASE_PATH from .env continues to work

## 3. Architecture Overview

No architecture change. This is a pure path reorganization:

```
Before:                              After:
apps/bot/config/jobs.json     →      config/jobs.json
apps/bot/config/mcp.json      →      config/mcp.json
apps/bot/config/models.yaml   →      config/models.yaml
apps/bot/config/logs/         →      output/logs/
apps/bot/data/                →      output/data/
data/synapulse.db             →      output/data/synapulse.db
```

## 4. Module Design

### 4.1 config/logging.py — Log path update

- Change `_logs_dir` from `Path(__file__).parent / "logs"` to project root `output/logs/`
- Use `_root` from settings.py for project root reference

### 4.2 config/settings.py — DATABASE_PATH default update

- Change default from `data/synapulse.db` to `output/data/synapulse.db`
- `_root` already defined here, export it for other modules

### 4.3 config/jobs.py — Jobs config path update

- Change `_CONFIG_PATH` from `Path(__file__).parent / "jobs.json"` to `_root / "config" / "jobs.json"`

### 4.4 core/handler.py — Config path updates

- Change `_STATIC_MCP_CONFIG` from `apps/bot/config/mcp.json` to `config/mcp.json`
- Change `_MODELS_CONFIG` from `apps/bot/config/models.yaml` to `config/models.yaml`
- Change `dynamic_config_path` to use `output/data/` directory
- Add startup directory creation: `config/`, `output/logs/`, `output/data/`

### 4.5 .gitignore update

- Add `output/` to ignore runtime output
- Add `config/jobs.json`, `config/mcp.json`, `config/models.yaml` to ignore user config
- Remove old paths: `/apps/bot/config/jobs.json`, `/apps/bot/config/logs/`, `/apps/bot/data/`, `/data/`

### 4.6 File moves

- Move `apps/bot/config/jobs.json` → `config/jobs.json`
- Move `apps/bot/config/jobs.json.example` → `config/jobs.json.example`
- Move `apps/bot/config/mcp.json` → `config/mcp.json`
- Move `apps/bot/config/models.yaml.example` → `config/models.yaml.example`
- Delete old `apps/bot/config/logs/` directory (output, not tracked)
- Delete old `apps/bot/data/` directory (data, not tracked)

## 5. Data Model

No change.

## 6. API Design

N/A.

## 7. Key Flows

Startup directory creation flow (added to handler.py start()):

1. `os.makedirs("config", exist_ok=True)`
2. `os.makedirs("output/logs", exist_ok=True)`
3. `os.makedirs("output/data", exist_ok=True)`
4. Continue existing startup flow

## 8. Shared Modules & Reuse Strategy

- `_root` in settings.py is the single source for project root path, reused by logging.py, jobs.py, and handler.py

## 9. Risks & Notes

- Users with existing data in old paths need to manually move their data files
- .env DATABASE_PATH overrides still work with absolute or relative paths

## 10. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version | ALL            | -      |
