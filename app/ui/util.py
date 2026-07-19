"""Small UI helpers: background task runner and error prettifier."""
from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal

log = logging.getLogger(__name__)


class _Signals(QObject):
    finished = Signal(object)


class Task(QRunnable):
    """Run `work()` in the Qt thread pool; deliver result or exception
    to `done(result_or_exception)` on the main thread."""

    def __init__(self, work: Callable[[], Any],
                 done: Callable[[Any], None]) -> None:
        super().__init__()
        self._work = work
        self._signals = _Signals()
        self._signals.finished.connect(done)

    def run(self) -> None:
        try:
            result = self._work()
        except Exception as e:  # deliver, never swallow silently
            log.error("Background task failed:\n%s",
                      traceback.format_exc())
            result = e
        self._signals.finished.emit(result)


def human_error(e: Exception) -> str:
    """Best human-readable message for any raised exception."""
    for attr in ("user_message",):
        msg = getattr(e, attr, None)
        if msg:
            return str(msg)
    return ("Something went wrong. Technical details were written to "
            "the application log.")
