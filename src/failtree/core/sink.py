"""ErrorSink protocol — capture talks to this, not to SQLite directly.

P0 future-proofing: SqliteSink today, HttpSink later without rewriting Tracker.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

from failtree.core.models import ItemStatus, NewError, RunStatus, RunSummary
from failtree.core.storage import Storage


class ErrorSink(Protocol):
    """Persistence port for capture events."""

    def start_run(
        self,
        label: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int: ...

    def finish_run(
        self, run_id: int, status: RunStatus = RunStatus.COMPLETED
    ) -> None: ...

    def heartbeat(self, run_id: int) -> None: ...

    def ensure_item(self, run_id: int, key: str, stage: str = "") -> int: ...

    def finalize_item(
        self,
        run_id: int,
        key: str,
        stage: str = "",
        *,
        status: ItemStatus = ItemStatus.OK,
        bump_attempts: bool = True,
    ) -> int: ...

    def insert_errors(self, errors: Sequence[NewError]) -> List[int]: ...

    def bump_group(
        self,
        *,
        fingerprint: str,
        title: str,
        error_id: int,
        ts: Optional[str] = None,
        sample_cap: int = 5,
    ) -> None: ...

    def get_summary(self, run_id: int) -> RunSummary: ...

    def close(self) -> None: ...


class SqliteSink:
    """Default sink: one local SQLite file (WAL)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.storage = Storage(self.path)

    def start_run(
        self,
        label: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        return self.storage.create_run(label=label, meta=meta)

    def finish_run(
        self, run_id: int, status: RunStatus = RunStatus.COMPLETED
    ) -> None:
        self.storage.finish_run(run_id, status)

    def heartbeat(self, run_id: int) -> None:
        self.storage.heartbeat(run_id)

    def ensure_item(self, run_id: int, key: str, stage: str = "") -> int:
        return self.storage.ensure_item(run_id, key, stage)

    def finalize_item(
        self,
        run_id: int,
        key: str,
        stage: str = "",
        *,
        status: ItemStatus = ItemStatus.OK,
        bump_attempts: bool = True,
    ) -> int:
        return self.storage.upsert_item(
            run_id, key, stage, status=status, bump_attempts=bump_attempts
        )

    def insert_errors(self, errors: Sequence[NewError]) -> List[int]:
        return self.storage.insert_errors(errors)

    def bump_group(
        self,
        *,
        fingerprint: str,
        title: str,
        error_id: int,
        ts: Optional[str] = None,
        sample_cap: int = 5,
    ) -> None:
        self.storage.bump_group(
            fingerprint=fingerprint,
            title=title,
            error_id=error_id,
            ts=ts,
            sample_cap=sample_cap,
        )

    def get_summary(self, run_id: int) -> RunSummary:
        return self.storage.get_summary(run_id)

    def close(self) -> None:
        self.storage.close()
