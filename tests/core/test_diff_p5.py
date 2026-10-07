from __future__ import annotations

from pathlib import Path

from failtree import Tracker
from failtree.cli import main
from failtree.core.diff import compare_runs, format_diff_report
from failtree.core.models import DiffKind
from failtree.core.storage import Storage
from failtree.viewer.loading import BrowserSession


def _run_with_failures(
    db: Path,
    *,
    value_n: int = 0,
    runtime_n: int = 0,
    keyerror_n: int = 0,
    oserror_n: int = 0,
) -> int:
    with Tracker(db, continue_on_error=True) as t:
        for i in range(value_n):
            with t.item(f"v{i}.csv", stage="parse"):
                raise ValueError(
                    f"bad id {i:08x}-e29b-41d4-a716-446655440000"
                )
        for i in range(runtime_n):
            with t.item(f"r{i}.csv", stage="parse"):
                raise RuntimeError(f"HTTP 503 for wellLogID={i}")
        for i in range(keyerror_n):
            with t.item(f"k{i}.csv", stage="parse"):
                raise KeyError(f"missing_{i}")
        for i in range(oserror_n):
            with t.item(f"o{i}.csv", stage="parse"):
                raise OSError(f"disk full on /tmp/x{i}.bin")
        with t.item("ok.csv", stage="parse"):
            pass
        return t.run_id


def test_compare_runs_classifies_new_fixed_persisting_regressed(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    # Same raise sites (shared helper) so fingerprints match across runs.
    before = _run_with_failures(db, value_n=32, runtime_n=5, keyerror_n=3)
    after = _run_with_failures(db, value_n=5, runtime_n=12, oserror_n=2)

    with Storage(db) as store:
        diff = compare_runs(store, before, after)

    assert diff.before_run_id == before
    assert diff.after_run_id == after

    assert any(d.kind == DiffKind.NEW for d in diff.all_deltas)
    assert any(d.kind == DiffKind.FIXED for d in diff.all_deltas)
    assert any(d.kind == DiffKind.PERSISTING for d in diff.all_deltas)
    assert any(d.kind == DiffKind.REGRESSED for d in diff.all_deltas)

    persisting = [d for d in diff.persisting if "ValueError" in d.title]
    assert persisting
    assert persisting[0].before_count == 32
    assert persisting[0].after_count == 5

    regressed = [d for d in diff.regressed if "RuntimeError" in d.title]
    assert regressed
    assert regressed[0].before_count == 5
    assert regressed[0].after_count == 12

    fixed = [d for d in diff.fixed if "KeyError" in d.title]
    assert fixed
    assert fixed[0].before_count == 3
    assert fixed[0].after_count == 0

    new = [d for d in diff.new if "OSError" in d.title]
    assert new
    assert new[0].before_count == 0
    assert new[0].after_count == 2

    report = format_diff_report(diff)
    assert "32 -> 5" in report
    assert "5 -> 12" in report
    assert "NEW:" in report
    assert "REGRESSED:" in report


def test_cli_diff(tmp_path: Path, capsys) -> None:
    db = tmp_path / "runs.db"
    before = _run_with_failures(db, value_n=3, runtime_n=1)
    after = _run_with_failures(db, value_n=1, runtime_n=4)
    assert main(["diff", str(db), str(before), str(after)]) == 0
    out = capsys.readouterr().out
    assert f"diff: run {before} -> run {after}" in out
    assert "persisting:" in out
    assert "regressed:" in out


def test_browser_session_compare(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    before = _run_with_failures(db, value_n=2)
    after = _run_with_failures(db, value_n=2, runtime_n=1)
    session = BrowserSession(db)
    try:
        pair = session.default_diff_pair()
        assert pair == (before, after)
        diff = session.compare_runs(before, after)
        assert len(diff.new) == 1
        assert len(diff.persisting) == 1
    finally:
        session.close()
