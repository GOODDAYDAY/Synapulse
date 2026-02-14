"""
Global configuration loaded from .env at project root.

This module only handles loading and displaying config values.
Validation of specific fields is delegated to each provider/channel
via their authenticate() / validate() methods — Config does NOT
know which fields belong to which implementation.
"""

import os
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import load_dotenv

import logging

_root = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_root / ".env")

logger = logging.getLogger("synapulse.config")

_MASKED_KEYWORDS = {"TOKEN", "SECRET", "KEY", "PASSWORD"}


def _mask(name: str, value: str) -> str:
    """Mask sensitive values for safe logging."""
    if not value:
        return "<empty>"
    if any(kw in name.upper() for kw in _MASKED_KEYWORDS):
        return f"{value[:4]}***" if len(value) > 4 else "***"
    return value


@dataclass(frozen=True)
class Config:
    # Channel
    CHANNEL_TYPE: str = os.getenv("CHANNEL_TYPE", "discord")
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")

    # AI
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "mock")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    AI_MODEL: str = os.getenv("AI_MODEL", "gpt-4o-mini")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Tools
    BRAVE_API_KEY: str = os.getenv("BRAVE_API_KEY", "")
    LOCAL_FILES_ALLOWED_PATHS: str = os.getenv("LOCAL_FILES_ALLOWED_PATHS", "")

    # Jobs — Gmail (secrets only; operational config in config/jobs.json)
    GMAIL_ADDRESS: str = os.getenv("GMAIL_ADDRESS", "")
    GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "")

    # Jobs — Outlook (secrets only; operational config in config/jobs.json)
    OUTLOOK_ADDRESS: str = os.getenv("OUTLOOK_ADDRESS", "")
    OUTLOOK_APP_PASSWORD: str = os.getenv("OUTLOOK_APP_PASSWORD", "")

    # General
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG")

    def log_summary(self) -> None:
        """Print all config values with secrets masked."""
        logger.info("--- Config loaded ---")
        for f in fields(self):
            logger.info("  %s = %s", f.name, _mask(f.name, getattr(self, f.name)))
        logger.info("---------------------")


config = Config()
