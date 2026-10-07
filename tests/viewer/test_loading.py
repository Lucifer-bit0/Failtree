from __future__ import annotations

import asyncio
from pathlib import Path

from failtree import Tracker
from failtree.viewer.app import FailtreeApp
from failtree.viewer.loading import BrowserSession


def _seed(db: Path) -> None:
    with Tracker(db, continue_on_error=True) as t:
        with t.item("a.csv", stage="parse"):
            raise ValueError("bad id 550e8400-e29b-41d4-a716-446655440000")
        with t.item("b.csv", stage="parse"):
            raise ValueError("bad id 123e4567-e89b-12d3-a456-426614174000")
        with t.item("ok.csv", stage="parse"):
            pass


def test_browser_session_lazy_queries(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    _seed(db)
    session = BrowserSession(db)
    try:
        summary = session.summary()
        assert summary is not None
        assert summary.failed == 2
        groups = session.list_groups()
        assert len(groups) == 1
        items = session.list_items_for_group(groups[0].fingerprint)
        assert {i.key for i in items} == {"a.csv", "b.csv"}
        roots = session.list_root_errors(items[0].id)
        assert roots
        assert session.get_error(roots[0].id) is not None
    finally:
        session.close()


def test_app_mounts_with_pilot(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    _seed(db)
    app = FailtreeApp([db])

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#tree") is not None
            header = app.query_one("#summary")
            text = header.renderable if hasattr(header, "renderable") else str(header)
            # SummaryHeader.update stores content — check via _renderable or refresh text
            assert "failtree" in str(text) or "failed" in str(header.render())

    asyncio.run(_run())
