"""Lazy data access for the Textual viewer (no Textual imports here)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from failtree.core.models import ErrorRecord, Group, Item, Run, RunSummary
from failtree.core.storage import Storage


@dataclass
class NodeRef:
    """Payload attached to each tree node."""

    kind: str  # group | item | error
    fingerprint: Optional[str] = None
    item_id: Optional[int] = None
    error_id: Optional[int] = None
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

    def list_runs(self) -> List[Run]:
        return self._storage.list_runs()

    def list_groups(
        self,
        *,
        query: Optional[str] = None,
        limit: int = 200,
    ) -> List[Group]:
        return self._storage.list_groups(query=query, limit=limit)

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


def open_sessions(paths: Sequence[Path]) -> List[BrowserSession]:
    return [BrowserSession(p) for p in paths]
