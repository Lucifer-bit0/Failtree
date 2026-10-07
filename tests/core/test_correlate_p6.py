from __future__ import annotations

import importlib.util
from pathlib import Path

from failtree import Tracker
from failtree.cli import main
from failtree.core.correlate import correlate_runs, format_correlation_report
from failtree.core.models import CorrelateRank
from failtree.core.storage import Storage


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_worker(path: Path, *, buggy: bool) -> None:
    if buggy:
        path.write_text(
            "def run_item(key):\n"
            "    # injected bug\n"
            "    raise ValueError(f'bad {key}')\n",
            encoding="utf-8",
        )
    else:
        path.write_text(
            "def run_item(key):\n"
            "    raise ValueError(f'bad {key}')\n",
            encoding="utf-8",
        )


def test_code_version_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAILTREE_GIT_SHA", "deadbeef42")
    db = tmp_path / "runs.db"
    with Tracker(db, project_roots=[tmp_path], continue_on_error=True) as t:
        with t.item("ok", stage="parse"):
            pass
        run_id = t.run_id
    with Storage(db) as store:
        run = store.get_run(run_id)
    assert run is not None
    assert run.code_version == "deadbeef42"
    assert run.code_version_source == "env"


def test_correlate_points_at_changed_function(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAILTREE_GIT_SHA", "sha-before")
    worker = tmp_path / "worker.py"
    _write_worker(worker, buggy=False)
    db = tmp_path / "runs.db"

    mod = _load(worker)
    with Tracker(db, project_roots=[tmp_path], continue_on_error=True) as t:
        with t.item("a.csv", stage="parse"):
            mod.run_item("a")
        before = t.run_id

    monkeypatch.setenv("FAILTREE_GIT_SHA", "sha-after")
    _write_worker(worker, buggy=True)
    mod = _load(worker)
    with Tracker(db, project_roots=[tmp_path], continue_on_error=True) as t:
        with t.item("a.csv", stage="parse"):
            mod.run_item("a")
        after = t.run_id

    with Storage(db) as store:
        files_before = store.list_run_files(before)
        files_after = store.list_run_files(after)
        assert files_before
        assert files_after
        assert files_before[0].content_hash != files_after[0].content_hash

        report = correlate_runs(store, before, after)
        assert report.before_version == "sha-before"
        assert report.after_version == "sha-after"
        assert report.changes
        top = report.changes[0]
        assert top.rank in (CorrelateRank.SAME_FUNCTION, CorrelateRank.SAME_FILE)
        assert top.confidence in ("high", "medium")
        assert "run_item" in (top.function or "") or "worker.py" in top.path
        assert top.unified_diff
        assert "injected bug" in top.unified_diff or "+    # injected" in top.unified_diff

        text = format_correlation_report(report)
        assert "correlation, not proof" in text
        assert "Likely" not in text or "likely" in text.lower() or "same_" in text


def test_correlate_none_when_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GIT_SHA", "same")
    worker = tmp_path / "worker.py"
    _write_worker(worker, buggy=False)
    db = tmp_path / "runs.db"
    mod = _load(worker)

    with Tracker(db, project_roots=[tmp_path], continue_on_error=True) as t:
        with t.item("a.csv", stage="parse"):
            mod.run_item("a")
        before = t.run_id
    with Tracker(db, project_roots=[tmp_path], continue_on_error=True) as t:
        with t.item("a.csv", stage="parse"):
            mod.run_item("a")
        after = t.run_id

    with Storage(db) as store:
        report = correlate_runs(store, before, after)
    assert report.message == "no related code change found"
    assert report.changes == ()


def test_cli_correlate(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FAILTREE_GIT_SHA", "v1")
    worker = tmp_path / "worker.py"
    _write_worker(worker, buggy=False)
    db = tmp_path / "runs.db"
    mod = _load(worker)
    with Tracker(db, project_roots=[tmp_path], continue_on_error=True) as t:
        with t.item("a.csv", stage="parse"):
            mod.run_item("a")
        before = t.run_id
    monkeypatch.setenv("FAILTREE_GIT_SHA", "v2")
    _write_worker(worker, buggy=True)
    mod = _load(worker)
    with Tracker(db, project_roots=[tmp_path], continue_on_error=True) as t:
        with t.item("a.csv", stage="parse"):
            mod.run_item("a")
        after = t.run_id

    assert main(["correlate", str(db), str(before), str(after)]) == 0
    out = capsys.readouterr().out
    assert f"correlate: run {before} -> run {after}" in out
    assert "correlation, not proof" in out
