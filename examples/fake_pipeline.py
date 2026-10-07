"""Fake ETL pipeline that demonstrates Tracker capture + grouping."""

from __future__ import annotations

import uuid
from pathlib import Path

from failtree import Tracker

DB = Path(__file__).resolve().parent / "fake_runs.db"
FILES = [f"file_{i}.csv" for i in range(12)]


def process(path: str) -> None:
    """Simulate parse failures with volatile ids/paths (same root causes)."""
    if path.endswith("_3.csv") or path.endswith("_7.csv"):
        raise ValueError(f"bad id {uuid.uuid4()} in /data/in/{path}")
    if path.endswith("_5.csv"):
        try:
            raise KeyError("address")
        except KeyError as exc:
            raise RuntimeError(f"cannot enrich {path}") from exc
    # success


def main() -> None:
    if DB.exists():
        DB.unlink()

    with Tracker(
        DB,
        label="fake-pipeline",
        project_roots=(Path(__file__).resolve().parent.parent / "src",),
        continue_on_error=True,
    ) as t:
        for path in FILES:
            with t.item(path, stage="parse"):
                process(path)

        summary = t.summary()
        print("Run summary")
        print(f"  total={summary.total} ok={summary.ok} failed={summary.failed}")
        print(f"  groups={summary.groups} recovered={summary.recovered}")
        print(f"DB: {DB}")
        print()
        print("Next (5-minute path):")
        print(f"  failtree summary {DB}")
        print(f"  failtree export {DB} -o retry.txt --stage parse")
        print(f"  failtree view {DB}")
        print("  python examples/correlate_demo.py")


if __name__ == "__main__":
    main()
