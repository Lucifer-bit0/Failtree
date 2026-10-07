"""Lazy data access for the Textual viewer (no Textual imports here)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from failtree.core.correlate import correlate_runs
from failtree.core.diff import compare_runs
from failtree.core.models import (
    CorrelationReport,
    ErrorRecord,
    Group,
    GroupImpact,
    Item,
    Run,
    RunDiff,
    RunSummary,
)
from failtree.core.storage import Storage


@dataclass
class NodeRef:
    """Payload attached to each tree node."""

    kind: str  # group | item | error | diff_section | diff_row
    fingerprint: Optional[str] = None
    item_id: Optional[int] = None
    error_id: Optional[int] = None
    diff_kind: Optional[str] = None
    before_count: Optional[int] = None
    after_count: Optional[int] = None
    title: Optional[str] = None
    loaded: bool = False


class BrowserSession:
    """Open one SQLite DB and serve lazy tree queries."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._storage = Storage(self.path)

    def close(self) -> None:
        self._storage.close()

    def latest_run_id(self) -> Optional[int]:
        return self._storage.latest_run_id()

    def summary(self, run_id: Optional[int] = None) -> Optional[RunSummary]:
        rid = run_id if run_id is not None else self.latest_run_id()
        if rid is None:
            return None
        return self._storage.get_summary(rid)

    def list_runs(self, *, limit: int = 50) -> List[Run]:
        return self._storage.list_runs(limit=limit)

    def list_groups(
        self,
        *,
        query: Optional[str] = None,
        limit: int = 200,
    ) -> List[Group]:
        return self._storage.list_groups(query=query, limit=limit)

    def rank_groups(
        self,
        *,
        run_id: Optional[int] = None,
        limit: int = 200,
    ) -> List[GroupImpact]:
        rid = run_id if run_id is not None else self.latest_run_id()
        if rid is None:
            return []
        return self._storage.rank_groups(rid, limit=limit)

    def list_items_for_group(
        self,
        fingerprint: str,
        *,
        run_id: Optional[int] = None,
        stage: Optional[str] = None,
    ) -> List[Item]:
        return self._storage.list_items_for_group(
            fingerprint, run_id=run_id, stage=stage
        )

    def list_root_errors(self, item_id: int) -> List[ErrorRecord]:
        return self._storage.list_root_errors_for_item(item_id)

    def list_child_errors(self, parent_error_id: int) -> List[ErrorRecord]:
        return self._storage.list_child_errors(parent_error_id)

    def get_error(self, error_id: int) -> Optional[ErrorRecord]:
        return self._storage.get_error(error_id)

    def get_item(self, item_id: int) -> Optional[Item]:
        return self._storage.get_item(item_id)

    def get_group(self, fingerprint: str) -> Optional[Group]:
        return self._storage.get_group(fingerprint)

    def export_failed(
        self,
        dest: Path,
        *,
        run_id: Optional[int] = None,
        stage: Optional[str] = None,
    ) -> int:
        from failtree.core.export import export_failed_keys

        rid = run_id if run_id is not None else self.latest_run_id()
        if rid is None:
            return 0
        return export_failed_keys(self._storage, rid, dest, stage=stage)

    def compare_runs(self, before_run_id: int, after_run_id: int) -> RunDiff:
        return compare_runs(self._storage, before_run_id, after_run_id)

    def correlate_runs(
        self,
        before_run_id: int,
        after_run_id: int,
        *,
        fingerprint: Optional[str] = None,
    ) -> CorrelationReport:
        return correlate_runs(
            self._storage,
            before_run_id,
            after_run_id,
            fingerprint=fingerprint,
        )

    def default_diff_pair(self) -> Optional[Tuple[int, int]]:
        """Return (before, after) for the two most recent runs, if available."""
        runs = self.list_runs(limit=2)
        if len(runs) < 2:
            return None
        # list_runs is newest-first
        after, before = runs[0].id, runs[1].id
        return before, after


def open_sessions(paths: Sequence[Path]) -> List[BrowserSession]:
    return [BrowserSession(p) for p in paths]
