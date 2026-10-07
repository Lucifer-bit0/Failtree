"""Bootstrap helpers: initialize failtree *before* service ``main`` runs.

Two integration styles:

1. **In-process** — ``failtree.run(main)`` wraps your entry function.
   Catches failures inside ``main`` and any imports that happen *from* main.

2. **Outer launcher** — ``failtree.run_command(["python", "app.py"])``
   (also ``failtree run -- …``) starts your process as a child and records
   non-zero exits / stderr, including import/syntax failures of that script.
"""

from __future__ import annotations

import subprocess
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TypeVar

from failtree.capture.tracker import Tracker

T = TypeVar("T")

_current_tracker: ContextVar[Optional[Tracker]] = ContextVar(
    "failtree_current_tracker", default=None
)


def get_tracker() -> Tracker:
    """Return the Tracker bound by :func:`run`, :func:`init`, or :func:`run_command`.

    Raises ``RuntimeError`` if called outside an active bootstrap.
    """
    tracker = _current_tracker.get()
    if tracker is None:
        from failtree.capture.init import get_global_tracker

        tracker = get_global_tracker()
    if tracker is None:
        raise RuntimeError(
            "No active failtree Tracker. Call failtree.init(...) / "
            "failtree.run(main), or create Tracker(...) yourself."
        )
    return tracker


def run(
    main: Callable[[], T],
    *,
    db_path: str | Path = "runs.db",
    label: Optional[str] = None,
    project_roots: Sequence[str | Path] | None = None,
    continue_on_error: bool = False,
    boot_key: str = "__main__",
    boot_stage: str = "boot",
    meta: Optional[dict[str, Any]] = None,
) -> T:
    """Initialize Tracker first, then call ``main()`` as a boot item.

    Typical service entry::

        from failtree import run, get_tracker

        def main() -> None:
            t = get_tracker()
            for item in work:
                with t.item(item, stage="parse"):
                    process(item)

        if __name__ == "__main__":
            run(main, db_path="runs.db", label="my-service")
    """
    with Tracker(
        db_path,
        label=label,
        project_roots=project_roots,
        continue_on_error=continue_on_error,
        meta=meta,
    ) as tracker:
        token = _current_tracker.set(tracker)
        try:
            with tracker.item(boot_key, stage=boot_stage):
                return main()
        finally:
            _current_tracker.reset(token)


def run_command(
    command: Sequence[str],
    *,
    db_path: str | Path = "runs.db",
    label: Optional[str] = None,
    project_roots: Sequence[str | Path] | None = None,
    stage: str = "process",
    meta: Optional[dict[str, Any]] = None,
) -> int:
    """Run an external command and record failures (incl. import/syntax errors).

    Use this from Docker ENTRYPOINT / supervisors when the child may die
    before it can import failtree itself.
    """
    if not command:
        raise ValueError("command must not be empty")

    key = " ".join(command)
    with Tracker(
        db_path,
        label=label or key[:80],
        project_roots=project_roots,
        continue_on_error=False,
        meta=meta,
    ) as tracker:
        token = _current_tracker.set(tracker)
        try:
            with tracker.item(key, stage=stage):
                proc = subprocess.run(
                    list(command),
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    stderr = (proc.stderr or "").strip()
                    stdout = (proc.stdout or "").strip()
                    detail = stderr or stdout or "(no output)"
                    # Keep message bounded for fingerprinting / SQLite.
                    detail = detail[-4000:]
                    raise RuntimeError(
                        f"command exited {proc.returncode}: {detail}"
                    )
                if proc.stdout:
                    sys.stdout.write(proc.stdout)
                if proc.stderr:
                    sys.stderr.write(proc.stderr)
                return int(proc.returncode)
        finally:
            _current_tracker.reset(token)
