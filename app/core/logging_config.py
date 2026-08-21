import logging
import logging.config
import logging.handlers
import os
import time
from pathlib import Path

# ── Read from environment ────────────────────────────────────────────────────
LOG_LEVEL       = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR         = Path(os.getenv("LOG_DIR", "logs"))
RETENTION_DAYS  = int(os.getenv("LOG_RETENTION_DAYS", "7"))
DEBUG_LOG_DIR   = Path(os.getenv("DEBUG_LOG_DIR", "pre_llm_logs"))

# Ensure log directories exist before handlers try to open files
LOG_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)

APP_LOG_FILE    = str(LOG_DIR / "app.log")
ACCESS_LOG_FILE = str(LOG_DIR / "access.log")

# ── Logging dict config ──────────────────────────────────────────────────────
LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,       # keep uvicorn / sqlalchemy loggers alive
    "formatters": {
        "standard": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "brief": {
            # Shorter format used for uvicorn access logs
            "format": "%(asctime)s | %(levelname)-8s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        # ── Console handlers ─────────────────────────────────────────────
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "standard",
            "level": LOG_LEVEL,
        },
        "access_console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "brief",
            "level": "INFO",
        },
        # ── Rotating file handlers ───────────────────────────────────────
        # TimedRotatingFileHandler rotates at midnight, keeps backupCount days
        "app_file": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": APP_LOG_FILE,
            "when": "midnight",          # rotate at midnight
            "interval": 1,              # every 1 day
            "backupCount": RETENTION_DAYS,
            "encoding": "utf-8",
            "formatter": "standard",
            "level": LOG_LEVEL,
        },
        "access_file": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": ACCESS_LOG_FILE,
            "when": "midnight",
            "interval": 1,
            "backupCount": RETENTION_DAYS,
            "encoding": "utf-8",
            "formatter": "brief",
            "level": "INFO",
        },
    },
    "loggers": {
        # ── Application loggers ──────────────────────────────────────────
        "app": {
            "handlers": ["console", "app_file"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        # ── Uvicorn loggers ──────────────────────────────────────────────
        "uvicorn": {
            "handlers": ["console", "app_file"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console", "app_file"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["access_console", "access_file"],
            "level": "INFO",
            "propagate": False,
        },
        # ── Third-party libraries (quieter by default) ───────────────────
        "httpx": {
            "handlers": ["console", "app_file"],
            "level": "WARNING",
            "propagate": False,
        },
        "qdrant_client": {
            "handlers": ["console", "app_file"],
            "level": "WARNING",
            "propagate": False,
        },
    },
    # Root logger — catches anything not matched above
    "root": {
        "handlers": ["console", "app_file"],
        "level": "WARNING",
    },
}


def cleanup_old_debug_logs() -> None:
    """Delete pre_llm_logs/*.jsonl files older than RETENTION_DAYS days.

    Mirrors the backupCount behaviour of TimedRotatingFileHandler used for
    logs/app.log and logs/access.log — ensuring both log directories age out
    on the same schedule controlled by LOG_RETENTION_DAYS.
    """
    cutoff = time.time() - RETENTION_DAYS * 86_400  # seconds in a day
    deleted = 0
    for log_file in DEBUG_LOG_DIR.glob("*.jsonl"):
        if log_file.stat().st_mtime < cutoff:
            log_file.unlink(missing_ok=True)
            deleted += 1
    return deleted


def setup_logging() -> None:
    """Apply the logging configuration and purge stale debug logs. Call once at startup."""
    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger("app")

    # Purge pre_llm_logs files older than LOG_RETENTION_DAYS — same policy as
    # TimedRotatingFileHandler's backupCount applied to logs/app.log.
    deleted = cleanup_old_debug_logs()
    logger.info(
        "Logging initialised | level=%s | log_dir=%s | debug_log_dir=%s | retention=%s days | pre_llm_logs_purged=%s",
        LOG_LEVEL, LOG_DIR.resolve(), DEBUG_LOG_DIR.resolve(), RETENTION_DAYS, deleted,
    )
