"""Enterprise logging: console, rotating file, error file and an audit trail.

Configure once with :func:`configure_logging`; obtain child loggers via
:func:`get_logger`. Secrets must be redacted *before* they reach a log call --
see :func:`webmon.security.redact`.
"""

from __future__ import annotations

import logging
import logging.handlers
from datetime import date
from pathlib import Path

from .config import LoggingConfig

_ROOT = "webmon"
_AUDIT = "webmon.audit"


def _console_handler(level: int) -> logging.Handler:
    try:
        from rich.logging import RichHandler

        handler: logging.Handler = RichHandler(
            level=level, rich_tracebacks=True, show_path=False, markup=False, log_time_format="[%X]"
        )
    except Exception:  # pragma: no cover
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    handler.setLevel(level)
    return handler


def _rotating(path: Path, cfg: LoggingConfig, level: int) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=cfg.rotate_max_bytes, backupCount=cfg.rotate_backup_count, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    return handler


def configure_logging(cfg: LoggingConfig, log_dir: Path, *, silent: bool = False) -> logging.Logger:
    """Configure the ``webmon`` logger hierarchy and return its root logger."""
    log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, cfg.level, logging.INFO)

    root = logging.getLogger(_ROOT)
    root.setLevel(level)
    root.propagate = False
    for existing in list(root.handlers):
        root.removeHandler(existing)
        existing.close()

    if cfg.console and not silent:
        root.addHandler(_console_handler(level))
    stamp = date.today().isoformat() if cfg.date_stamped_files else "current"
    root.addHandler(_rotating(log_dir / f"webmon-{stamp}.log", cfg, level))
    root.addHandler(_rotating(log_dir / "errors.log", cfg, logging.WARNING))

    if cfg.audit_log:
        audit = logging.getLogger(_AUDIT)
        audit.setLevel(logging.INFO)
        audit.propagate = False
        for existing in list(audit.handlers):
            audit.removeHandler(existing)
            existing.close()
        handler = logging.handlers.RotatingFileHandler(
            log_dir / "audit.log", maxBytes=cfg.rotate_max_bytes,
            backupCount=max(cfg.rotate_backup_count, 3), encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s | AUDIT | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        audit.addHandler(handler)
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``webmon`` namespace."""
    if not name.startswith(_ROOT):
        name = f"{_ROOT}.{name}"
    return logging.getLogger(name)


def audit(message: str, **fields: object) -> None:
    """Append a structured entry to the audit trail."""
    logger = logging.getLogger(_AUDIT)
    if fields:
        extras = " ".join(f"{k}={v}" for k, v in fields.items())
        logger.info("%s %s", message, extras)
    else:
        logger.info("%s", message)
