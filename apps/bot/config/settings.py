import logging
import os
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import load_dotenv

_root = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_root / ".env")

logger = logging.getLogger("synapulse.config")

_MASKED_KEYWORDS = {"TOKEN", "SECRET", "KEY", "PASSWORD"}


def _mask(name: str, value: str) -> str:
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
    AI_MODEL: str = os.getenv("AI_MODEL", "gpt-4o-mini")

    # General
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG")

    def validate(self) -> None:
        missing = []
        if self.CHANNEL_TYPE == "discord" and not self.DISCORD_TOKEN:
            missing.append("DISCORD_TOKEN")
        if self.AI_PROVIDER == "github" and not self.GITHUB_TOKEN:
            missing.append("GITHUB_TOKEN")
        if missing:
            raise EnvironmentError(
                f"Required env var(s) not set: {', '.join(missing)}. "
                f"Check your .env file at {_root / '.env'}"
            )

    def log_summary(self) -> None:
        logger.info("--- Config loaded ---")
        for f in fields(self):
            logger.info("  %s = %s", f.name, _mask(f.name, getattr(self, f.name)))
        logger.info("---------------------")


config = Config()
