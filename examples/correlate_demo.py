"""Offline demo for P6 code-change correlation.

Runs the same failing worker twice, edits the worker between runs, then prints
``failtree correlate``. No network required.

Usage:
  python examples/correlate_demo.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from failtree import Tracker
from failtree.core.correlate import correlate_runs, format_correlation_report
from failtree.core.storage import Storage

ROOT = Path(__file__).resolve().parent
DB = ROOT / "correlate_demo.db"
WORKER = ROOT / "_correlate_worker.py"

WORKER_V1 = '''\
"""Demo worker - version 1 (before)."""

def process(key: str) -> None:
    raise ValueError(f"bad record {key}")
'''

WORKER_V2 = '''\
"""Demo worker - version 2 (after): injected bug comment + same failure."""

def process(key: str) -> None:
    # injected bug: stricter validation
    raise ValueError(f"bad record {key}")
'''


def _load_worker():
    spec = importlib.util.spec_from_file_location("_correlate_worker", WORKER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_once(label: str, git_sha: str) -> int:
    os.environ["FAILTREE_GIT_SHA"] = git_sha
    mod = _load_worker()
    with Tracker(
        DB,
        label=label,
        project_roots=(ROOT,),
        continue_on_error=True,
    ) as t:
        for i in range(6):
            with t.item(f"row_{i}.csv", stage="parse"):
                mod.process(f"row_{i}")
        return t.run_id


def main() -> int:
    if DB.exists():
        DB.unlink()
    for suffix in ("-wal", "-shm"):
        side = Path(str(DB) + suffix)
        if side.exists():
            side.unlink()

    print("correlate demo")
    print(f"  db={DB}")
    print(f"  worker={WORKER}")
    print()

    WORKER.write_text(WORKER_V1, encoding="utf-8")
    before = _run_once("correlate-before", "sha-before")
    print(f"  run {before}: FAILTREE_GIT_SHA=sha-before  worker=v1")

    WORKER.write_text(WORKER_V2, encoding="utf-8")
    after = _run_once("correlate-after", "sha-after")
    print(f"  run {after}: FAILTREE_GIT_SHA=sha-after   worker=v2 (edited)")
    print()

    with Storage(DB) as store:
        report = correlate_runs(store, before, after)
        print(format_correlation_report(report))

    print()
    print("Re-run anytime:")
    print(f"  python {Path(__file__).as_posix()}")
    print(f"  python -m failtree.cli correlate {DB.as_posix()} {before} {after}")
    return 0 if report.changes else 1


if __name__ == "__main__":
    sys.exit(main())
