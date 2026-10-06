from __future__ import annotations

from pathlib import Path

from failtree import Tracker
from failtree.cli import main


def test_cli_summary_and_export(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    with Tracker(db, continue_on_error=True) as t:
        with t.item("a.csv", stage="parse"):
            raise ValueError("nope")
        with t.item("b.csv", stage="parse"):
            pass

    assert main(["summary", str(db)]) == 0
    out = tmp_path / "retry.txt"
    assert main(["export", str(db), "-o", str(out), "--stage", "parse"]) == 0
    assert out.read_text(encoding="utf-8").strip() == "a.csv"
