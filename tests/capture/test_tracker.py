from __future__ import annotations

from pathlib import Path

from failtree import Tracker


def test_tracker_item_success_and_failure(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    with Tracker(db, label="t", continue_on_error=True) as t:
        with t.item("ok.csv", stage="parse"):
            pass
        with t.item("bad.csv", stage="parse"):
            raise ValueError("bad id 550e8400-e29b-41d4-a716-446655440000")
        with t.item("bad2.csv", stage="parse"):
            raise ValueError("bad id 123e4567-e89b-12d3-a456-426614174000")

        summary = t.summary()
        assert summary.total == 3
        assert summary.ok == 1
        assert summary.failed == 2
        assert summary.groups == 1

    # reopen and check persistence
    from failtree.core.storage import Storage

    with Storage(db) as store:
        run_id = store.latest_run_id()
        assert run_id is not None
        keys = store.iter_failed_keys(run_id, stage="parse")
        assert keys == ["bad.csv", "bad2.csv"]
        groups = store.list_groups()
        assert len(groups) == 1
        assert groups[0].count == 2


def test_tracker_reraises_without_continue(tmp_path: Path) -> None:
    with Tracker(tmp_path / "runs.db", continue_on_error=False) as t:
        try:
            with t.item("x"):
                raise RuntimeError("boom")
        except RuntimeError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("expected re-raise")


def test_decorator_track(tmp_path: Path) -> None:
    t = Tracker(tmp_path / "runs.db", continue_on_error=True)

    @t.track(stage="load")
    def load(path: str) -> str:
        if path == "bad":
            raise KeyError("missing")
        return path.upper()

    with t:
        assert load("good") == "GOOD"
        load("bad")
        summary = t.summary()
        assert summary.ok == 1
        assert summary.failed == 1


def test_cause_chain_persisted(tmp_path: Path) -> None:
    with Tracker(tmp_path / "runs.db", continue_on_error=True) as t:
        with t.item("x", stage="enrich"):
            try:
                raise KeyError("address")
            except KeyError as exc:
                raise RuntimeError("enrich failed") from exc

        item_id = t.storage.ensure_item(t.run_id, "x", "enrich")
        errors = t.storage.list_errors_for_item(item_id)
        assert len(errors) == 2
        root = next(e for e in errors if e.parent_error_id is None)
        child = next(e for e in errors if e.parent_error_id is not None)
        assert root.exc_type == "RuntimeError"
        assert child.exc_type == "KeyError"
        assert child.parent_error_id == root.id
        assert child.is_group_root is True
        assert t.storage.list_child_errors(root.id)[0].id == child.id
