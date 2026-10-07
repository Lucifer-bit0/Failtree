"""Process-level ``failtree.init()`` entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from failtree.capture.bootstrap import _current_tracker
from failtree.capture.hooks import install_hooks, uninstall_hooks
from failtree.capture.tracker import Tracker
from failtree.core.fingerprint import FingerprintConfig
from failtree.core.sink import ErrorSink

_global_tracker: Optional[Tracker] = None


def init(
    db_path: str | Path = "runs.db",
    *,
    sink: ErrorSink | None = None,
    label: Optional[str] = None,
    project_roots: Sequence[str | Path] | None = None,
    continue_on_error: bool = True,
    fingerprint_config: Optional[FingerprintConfig] = None,
    meta: Optional[Dict[str, Any]] = None,
    install_process_hooks: bool = True,
    heartbeat_interval: float = 30.0,
    redact: bool = True,
    extra_redact_patterns: Sequence[tuple[str, str]] = (),
) -> Tracker:
    """Initialize a process-wide Tracker (call once near process start).

    Example::

        import failtree
        failtree.init("runs.db", label="my-service")

        def main() -> None:
            t = failtree.get_tracker()
            with t.item("x", stage="parse"):
                ...
    """
    global _global_tracker
    if _global_tracker is not None and not _global_tracker._closed:  # noqa: SLF001
        return _global_tracker

    tracker = Tracker(
        db_path if sink is None else None,
        sink=sink,
        label=label,
        project_roots=project_roots,
        continue_on_error=continue_on_error,
        fingerprint_config=fingerprint_config,
        meta=meta,
        redact=redact,
        extra_redact_patterns=extra_redact_patterns,
        heartbeat_interval=heartbeat_interval,
    )
    _global_tracker = tracker
    _current_tracker.set(tracker)
    if install_process_hooks:
        install_hooks(tracker)
    return tracker


def shutdown(*, status: str = "completed") -> None:
    """Close the process-wide Tracker and uninstall hooks."""
    global _global_tracker
    from failtree.core.models import RunStatus

    uninstall_hooks()
    if _global_tracker is not None:
        try:
            _global_tracker.close(status=RunStatus(status))
        except Exception:
            pass
        _global_tracker = None


def get_global_tracker() -> Optional[Tracker]:
    return _global_tracker
