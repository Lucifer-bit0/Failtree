from __future__ import annotations

from pathlib import Path

from failtree.common.timeutil import utc_now_iso
from failtree.core.grouping import GroupService, append_example_id
from failtree.core.models import ItemStatus, NewError, RunStatus
from failtree.core.storage import Storage


def test_append_example_id_cap() -> None:
    ids = append_example_id([1, 2], 3, sample_cap=2)
    assert ids == [1, 2]
    ids = append_example_id([1], 2, sample_cap=2)
    assert ids == [1, 2]


def test_run_item_error_group_flow(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    with Storage(db) as store:
        run_id = store.create_run(label="t", meta={"env": "test"})
        item_id = store.upsert_item(run_id, "a.csv", "parse", status=ItemStatus.FAILED)

        ts = utc_now_iso()
        ids = store.insert_errors(
            [
                NewError(
                    item_id=item_id,
                    parent_error_id=None,
                    depth=0,
                    exc_type="ValueError",
                    message="bad",
                    normalized_message="bad",
                    traceback="Traceback...",
                    fingerprint="fp1",
                    ts=ts,
                    is_group_root=True,
                )
            ]
        )
        assert len(ids) == 1

        groups = GroupService(store, sample_cap=5)
        groups.bump(fingerprint="fp1", title="ValueError: bad", error_id=ids[0], ts=ts)
        groups.bump(fingerprint="fp1", title="ValueError: bad", error_id=ids[0], ts=ts)

        group = store.get_group("fp1")
        assert group is not None
        assert group.count == 2
        assert group.example_ids == (ids[0],)

        summary = store.get_summary(run_id)
        assert summary.total == 1
        assert summary.failed == 1
        assert summary.groups == 1

        store.finish_run(run_id, RunStatus.COMPLETED)
        run = store.get_run(run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.meta["env"] == "test"


def test_failed_keys_export_query(tmp_path: Path) -> None:
    with Storage(tmp_path / "runs.db") as store:
        run_id = store.create_run()
        store.upsert_item(run_id, "a.csv", "parse", status=ItemStatus.FAILED)
        store.upsert_item(run_id, "b.csv", "parse", status=ItemStatus.OK)
        store.upsert_item(run_id, "c.csv", "load", status=ItemStatus.FAILED)

        keys = store.iter_failed_keys(run_id, stage="parse")
        assert keys == ["a.csv"]


def test_parent_error_index_convention(tmp_path: Path) -> None:
    with Storage(tmp_path / "runs.db") as store:
        run_id = store.create_run()
        item_id = store.upsert_item(run_id, "x", status=ItemStatus.FAILED)
        ts = utc_now_iso()
        ids = store.insert_errors(
            [
                NewError(
                    item_id=item_id,
                    parent_error_id=None,
                    depth=0,
                    exc_type="RuntimeError",
                    message="outer",
                    normalized_message="outer",
                    traceback="",
                    fingerprint="outer",
                    ts=ts,
                    is_group_root=False,
                ),
                NewError(
                    item_id=item_id,
                    parent_error_id=-1,  # parent = index 0
                    depth=1,
                    exc_type="ValueError",
                    message="inner",
                    normalized_message="inner",
                    traceback="",
                    fingerprint="inner",
                    ts=ts,
                    is_group_root=True,
                ),
            ]
        )
        child = store.get_error(ids[1])
        assert child is not None
        assert child.parent_error_id == ids[0]
