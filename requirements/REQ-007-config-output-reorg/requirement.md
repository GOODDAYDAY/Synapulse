# REQ-007 Config & Output Directory Reorganization

> Status: Requirement Finalized
> Created: 2026-03-10
> Updated: 2026-03-10

## 1. Background

Current Synapulse project has configuration and output files scattered across multiple nested directories:

- Runtime config files (jobs.json, mcp.json, models.yaml) buried in `apps/bot/config/`
- Log files stored inside `apps/bot/config/logs/` (config directory should not produce output)
- Conversation data in `apps/bot/data/`
- Database path uses relative path `data/synapulse.db`

This makes deployment, maintenance, and Docker volume mapping unnecessarily complex. All runtime config should be in one
place, and all output/data should be in another.

## 2. Target Users & Scenarios

- **Developer**: quickly locate all config files and runtime output during development
- **Ops/Deployment**: mount only `config/` and `output/` directories for deployment
- **Docker**: clean volume mapping — `config/` for read-only config, `output/` for writable data

## 3. Functional Requirements

### F-01 Unified Runtime Config Directory

- Main flow:
    - Move `apps/bot/config/jobs.json` → `config/jobs.json`
    - Move `apps/bot/config/jobs.json.example` → `config/jobs.json.example`
    - Move `apps/bot/config/mcp.json` → `config/mcp.json`
    - Move `apps/bot/config/models.yaml.example` → `config/models.yaml.example`
    - Runtime `models.yaml` (user-created) will be expected at `config/models.yaml`
    - All code referencing these config file paths must be updated
- Error handling:
    - If `config/` directory does not exist at startup, create it automatically
    - Missing config files should produce clear error messages with the new expected path
- Edge cases:
    - `.env` and `.env.example` remain at project root (unchanged)
    - Python code modules (settings.py, prompts.py, logging.py, models.py, jobs.py) stay in `apps/bot/config/` — they
      are source code, not runtime config

### F-02 Unified Output Directory

- Main flow:
    - Create `output/` at project root with subdirectories `logs/` and `data/`
    - Logs: `apps/bot/config/logs/` → `output/logs/`
    - Conversation data: `apps/bot/data/conversations.json` → `output/data/conversations.json`
    - Database: default path → `output/data/synapulse.db`
    - Update `logging.py` log file path configuration
    - Update `settings.py` DATABASE_PATH default value
    - Update all code referencing data/conversation file paths
- Error handling:
    - Auto-create `output/logs/` and `output/data/` at startup if they don't exist
- Edge cases:
    - If user's `.env` has custom DATABASE_PATH pointing to old location, it continues to work (backward compatible)

### F-03 Auto-Create Directories

- Main flow:
    - On bot startup, ensure `config/`, `output/logs/`, `output/data/` exist
    - Use `os.makedirs(exist_ok=True)` pattern
- Error handling:
    - If directory creation fails (permission denied), log error and exit gracefully

### F-04 Update .gitignore

- Main flow:
    - Add `output/` to .gitignore (runtime output should not be tracked)
    - Add `config/jobs.json`, `config/mcp.json`, `config/models.yaml` to .gitignore (contain user-specific config)
    - Keep `config/*.example` files tracked (templates for users)
    - Remove old ignore rules for `apps/bot/config/logs/` if present
- Edge cases:
    - Preserve all existing .gitignore rules that are still relevant

## 4. Non-functional Requirements

- **Backward compatibility**: custom DATABASE_PATH in .env still works with old paths
- **Zero downtime**: pure path reorganization, no functional logic changes
- **Test isolation**: existing tests use temp files/mocks, should not be affected

## 5. Out of Scope

- Python source code modules stay in `apps/bot/config/` (not moved)
- `.env` location unchanged
- `requirements.txt` location unchanged
- No new config loading framework introduced
- No changes to config file format or content

## 6. Acceptance Criteria

| ID    | Feature | Condition                                 | Expected Result                                                                        |
|:------|:--------|:------------------------------------------|:---------------------------------------------------------------------------------------|
| AC-01 | F-01    | Check project root `config/` directory    | Contains jobs.json, mcp.json, models.yaml and their .example files                     |
| AC-02 | F-01    | Start bot                                 | Correctly reads config files from `config/`                                            |
| AC-03 | F-02    | Start bot and let it run                  | Logs written to `output/logs/bot.log`                                                  |
| AC-04 | F-02    | Trigger a conversation                    | Conversation data stored in `output/data/`                                             |
| AC-05 | F-02    | Database operation                        | Database file at `output/data/synapulse.db`                                            |
| AC-06 | F-03    | Delete `output/` directory then start bot | Directories auto-created                                                               |
| AC-07 | F-04    | Run `git status`                          | `output/` not tracked; `config/*.example` tracked; `config/jobs.json` etc. not tracked |

## 7. Change Log

| Version | Date       | Changes         | Affected Scope | Reason |
|:--------|:-----------|:----------------|:---------------|:-------|
| v1      | 2026-03-10 | Initial version | ALL            | -      |
