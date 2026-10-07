from __future__ import annotations

import sys
from pathlib import Path

from failtree import Tracker
from failtree.core.models import Gate
from failtree.core.storage import Storage
from failtree.core.summary import format_summary_report, rank_groups, summarize_run


def test_failure_rate_ranking(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    with Tracker(db, continue_on_error=True) as t:
        for i in range(6):
            with t.item(f"a{i}.csv", stage="parse"):
                raise ValueError(f"bad id {i}0000000-e29b-41d4-a716-446655440000")
        for i in range(2):
            with t.item(f"b{i}.csv", stage="parse"):
                raise RuntimeError(f"HTTP 503 for wellLogID={i}")
        with t.item("ok.csv", stage="parse"):
            pass
        run_id = t.run_id

    with Storage(db) as store:
        summary = summarize_run(store, run_id)
        assert summary.total == 9
        assert summary.ok == 1
        assert summary.failed == 8
        impacts = rank_groups(store, run_id)
        assert len(impacts) == 2
        assert impacts[0].failed_items == 6
        assert impacts[0].pct_of_failures == 75.0
        assert impacts[1].failed_items == 2
        assert impacts[1].pct_of_failures == 25.0
        report = format_summary_report(summary, impacts)
        assert "75.0%" in report
        assert "retried:" in report


def test_exception_group_gets_or_gate(tmp_path: Path) -> None:
    if sys.version_info < (3, 11):
        from exceptiongroup import ExceptionGroup as EG
    else:
        EG = ExceptionGroup  # noqa: F821

    db = tmp_path / "runs.db"
    with Tracker(db, continue_on_error=True) as t:
        with t.item("batch", stage="parse"):
            raise EG("many", [ValueError("one"), TypeError("two")])
        item_id = t.storage.ensure_item(t.run_id, "batch", "parse")
        errors = t.storage.list_errors_for_item(item_id)

    roots = [e for e in errors if e.parent_error_id is None]
    assert roots
    assert roots[0].gate == Gate.OR


def test_explicit_and_gate(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    with Tracker(db, continue_on_error=True) as t:
        with t.item("x", stage="validate", gate="AND"):
            raise RuntimeError("both paths failed")
        item_id = t.storage.ensure_item(t.run_id, "x", "validate")
        errors = t.storage.list_errors_for_item(item_id)
    assert errors[0].gate == Gate.AND
