"""Optional global hooks so uncaught errors still reach failtree.

Fail-open: hook failures never replace the original exception path.
"""

from __future__ import annotations

import logging
import sys
import threading
from types import TracebackType
from typing import TYPE_CHECKING, Any, Optional, Type

if TYPE_CHECKING:
    from failtree.capture.tracker import Tracker

_installed_for: Optional["Tracker"] = None
_prev_sys_excepthook = sys.excepthook
_prev_threading_excepthook = getattr(threading, "excepthook", None)


class FailtreeLogHandler(logging.Handler):
    """Forward logging records with exc_info into the active Tracker."""

    def __init__(self, tracker: "Tracker") -> None:
        super().__init__(level=logging.ERROR)
        self._tracker = tracker

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not record.exc_info:
                return
            exc = record.exc_info[1]
            if exc is None:
                return
            self._tracker.capture_exception(
                exc,
                key=f"log:{record.name}",
                stage="logging",
            )
        except Exception:  # pragma: no cover - fail open
            pass


def install_hooks(tracker: "Tracker") -> None:
    """Install process-wide hooks bound to ``tracker``."""
    global _installed_for, _prev_sys_excepthook, _prev_threading_excepthook
    _installed_for = tracker
    _prev_sys_excepthook = sys.excepthook
    sys.excepthook = _sys_excepthook  # type: ignore[assignment]

    if hasattr(threading, "excepthook"):
        _prev_threading_excepthook = threading.excepthook
        threading.excepthook = _threading_excepthook  # type: ignore[assignment]

    if hasattr(sys, "unraisablehook"):
        sys.unraisablehook = _unraisablehook  # type: ignore[assignment]

    root = logging.getLogger()
    if not any(isinstance(h, FailtreeLogHandler) for h in root.handlers):
        root.addHandler(FailtreeLogHandler(tracker))


def uninstall_hooks() -> None:
    """Restore previous hooks (best-effort)."""
    global _installed_for
    sys.excepthook = _prev_sys_excepthook
    if _prev_threading_excepthook is not None and hasattr(threading, "excepthook"):
        threading.excepthook = _prev_threading_excepthook
    _installed_for = None


def _sys_excepthook(
    exc_type: Type[BaseException],
    exc: BaseException,
    tb: Optional[TracebackType],
) -> None:
    tracker = _installed_for
    if tracker is not None:
        try:
            tracker.capture_exception(exc, key="__uncaught__", stage="excepthook")
        except Exception:
            pass
    _prev_sys_excepthook(exc_type, exc, tb)


def _threading_excepthook(args: Any) -> None:
    tracker = _installed_for
    exc = getattr(args, "exc_value", None)
    if tracker is not None and isinstance(exc, BaseException):
        try:
            tracker.capture_exception(exc, key="__thread__", stage="threading")
        except Exception:
            pass
    if _prev_threading_excepthook is not None:
        _prev_threading_excepthook(args)


def _unraisablehook(unraisable: Any) -> None:
    tracker = _installed_for
    exc = getattr(unraisable, "exc_value", None)
    if tracker is not None and isinstance(exc, BaseException):
        try:
            tracker.capture_exception(exc, key="__unraisable__", stage="unraisable")
        except Exception:
            pass
    # Prefer default formatting when available.
    default = getattr(sys, "__unraisablehook__", None)
    if callable(default):
        default(unraisable)
