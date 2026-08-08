"""
Structured logging setup.
Supports both human-readable text format (development) and
JSON format (production / log aggregators like Datadog, CloudWatch).
"""

import logging
import sys
from typing import Any

from app.core.config import settings

# ── Custom Formatter ───────────────────────────────────────────────────────────


class TextFormatter(logging.Formatter):
    """Colored, readable formatter for development."""

    GREY = "\x1b[38;5;240m"
    CYAN = "\x1b[36m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    LEVEL_COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: CYAN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, self.RESET)
        level = f"{color}{record.levelname:<8}{self.RESET}"
        name = f"{self.GREY}{record.name}{self.RESET}"
        message = super().format(record)
        # Strip the default formatting, rebuild cleanly
        record.levelname = record.levelname  # keep original for base
        return f"{level} | {name} | {record.getMessage()}"


class JSONFormatter(logging.Formatter):
    """JSON formatter for production log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        import datetime

        log_record: dict[str, Any] = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


# ── Setup Function ─────────────────────────────────────────────────────────────


def setup_logging() -> None:
    """
    Configure root logger and silence noisy third-party loggers.
    Call once at application startup.
    """
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Root handler
    handler = logging.StreamHandler(sys.stdout)

    if settings.LOG_FORMAT == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Silence noisy libraries — keep our signal clean
    for noisy in ("httpx", "httpcore", "uvicorn.access", "supabase"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Keep uvicorn error logs visible
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging configured | level={settings.LOG_LEVEL} "
        f"format={settings.LOG_FORMAT} env={settings.APP_ENV}"
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger. Use this in every module:
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)
