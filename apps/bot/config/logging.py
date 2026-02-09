import logging
import logging.config
from pathlib import Path

_logs_dir = Path(__file__).resolve().parent / "logs"
_logs_dir.mkdir(exist_ok=True)


def _build_config(level: str = "DEBUG") -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "brief": {
                "format": "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
                "datefmt": "%H:%M:%S",
            },
            "detailed": {
                "format": (
                    "%(asctime)s [%(levelname)-8s] %(name)s "
                    "(%(filename)s:%(lineno)d) %(funcName)s: %(message)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "brief",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "DEBUG",
                "formatter": "detailed",
                "filename": str(_logs_dir / "bot.log"),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "synapulse": {
                "level": level,
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "discord": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
        "root": {
            "level": "WARNING",
            "handlers": ["console", "file"],
        },
    }


def setup_logging(level: str = "DEBUG") -> None:
    logging.config.dictConfig(_build_config(level))
    logger = logging.getLogger("synapulse.logging")
    logger.info("Logging initialized (level=%s, log_file=%s)", level, _logs_dir / "bot.log")
