"""
Hot-reloadable job configuration from jobs.json.

Each call to load_job_config() re-reads the file from disk,
so changes take effect on the next tick without restarting the bot.

If jobs.json is missing or contains invalid JSON, all jobs are
treated as disabled until the file is fixed.
"""

import json
from pathlib import Path

import logging

logger = logging.getLogger("synapulse.config")

_CONFIG_PATH = Path(__file__).resolve().parent / "jobs.json"


def load_job_config(name: str) -> dict:
    """Load config for a single job by name.

    Returns the job's config dict from jobs.json, or {"enabled": False}
    if the file is missing, unparseable, or has no entry for this job.
    """
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return data.get(name, {"enabled": False})
    except FileNotFoundError:
        logger.warning("jobs.json not found at %s — all jobs disabled", _CONFIG_PATH)
        return {"enabled": False}
    except json.JSONDecodeError as e:
        logger.warning("jobs.json parse error: %s — all jobs disabled", e)
        return {"enabled": False}
