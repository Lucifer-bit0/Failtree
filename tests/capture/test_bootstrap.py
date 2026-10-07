from __future__ import annotations

import sys
from pathlib import Path

import pytest

from failtree import get_tracker, run, run_command
from failtree.core.storage import Storage


def test_run_wraps_main_and_exposes_tracker(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    seen: list[int] = []

    def main() -> str:
        t = get_tracker()
        seen.append(t.run_id)
        with t.item("a", stage="work"):
            return "ok"

    assert run(main, db_path=db, label="boot-demo") == "ok"
    with Storage(db) as store:
        summary = store.get_summary(store.latest_run_id())  # type: ignore[arg-type]
        # boot item + work item
        assert summary.total == 2
        assert summary.ok == 2
        assert seen and seen[0] == summary.run_id


def test_run_records_boot_failure(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"

    def main() -> None:
        raise ImportError("No module named 'missing_lib'")

    with pytest.raises(ImportError):
        run(main, db_path=db, label="boot-fail")

    with Storage(db) as store:
        rid = store.latest_run_id()
        assert rid is not None
        summary = store.get_summary(rid)
        assert summary.failed == 1
        assert summary.groups == 1


def test_get_tracker_outside_bootstrap() -> None:
    with pytest.raises(RuntimeError, match="No active failtree Tracker"):
        get_tracker()


def test_run_command_records_import_failure(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    broken = tmp_path / "broken_app.py"
    broken.write_text("import totally_missing_package_xyz\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="exited"):
        run_command(
            [sys.executable, str(broken)],
            db_path=db,
            label="child-import",
        )

    with Storage(db) as store:
        rid = store.latest_run_id()
        assert rid is not None
        summary = store.get_summary(rid)
        assert summary.failed == 1
        groups = store.list_groups()
        assert groups
        assert groups[0].count == 1
        # Child import failure is wrapped as RuntimeError with stderr detail.
        assert "exited" in groups[0].title or "Error" in groups[0].title
