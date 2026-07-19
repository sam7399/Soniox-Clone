"""Rotating file logging under the app data folder. Console output only
in development. User-facing surfaces never show raw tracebacks."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from app.config import app_data_dir


def setup_logging(level: int = logging.INFO) -> None:
    logs = app_data_dir() / "logs"
    logs.mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            logs / "globalvoice.log", maxBytes=2_000_000, backupCount=5,
            encoding="utf-8")
    ]
    if not getattr(sys, "frozen", False):
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
