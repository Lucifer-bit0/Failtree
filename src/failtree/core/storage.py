"""SQLite persistence for runs, items, errors, and groups."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from failtree.common.jsonutil import dumps_json, loads_json
from failtree.common.timeutil import parse_iso, utc_now_iso
from failtree.core.models import (
    ErrorRecord,
    Group,
    Item,
    ItemStatus,
    NewError,
    Run,
    RunStatus,
    RunSummary,
)
from failtree.core.grouping import append_example_id
from failtree.core.schema import DDL, PRAGMAS, SCHEMA_VERSION


class Storage:
    """Single entry point for DB I/O. Thread-safe writes via an RLock."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            isolation_level=None,  # we manage transactions explicitly
        )
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- connection helpers -------------------------------------------------

    def _configure(self) -> None:
        for pragma in PRAGMAS:
            self._conn.execute(pragma)

    def _migrate(self) -> None:
        # executescript() commits internally — do not wrap it in _transaction.
        with self._lock:
            self._conn.executescript(DDL)
            row = self._conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version(version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
            elif int(row["version"]) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported schema version {row['version']}; "
                    f"expected {SCHEMA_VERSION}"
                )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # --- runs ---------------------------------------------------------------

    def create_run(
        self,
        label: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        started = utc_now_iso()
        meta_json = dumps_json(meta or {})
        with self._transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs(label, started_at, status, meta_json)
                VALUES (?, ?, ?, ?)
                """,
                (label, started, RunStatus.RUNNING.value, meta_json),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: RunStatus = RunStatus.COMPLETED) -> None:
        with self._transaction() as conn:
            conn.execute(
                """
                UPDATE runs
                SET ended_at = ?, status = ?
                WHERE id = ?
                """,
                (utc_now_iso(), status.value, run_id),
            )

    def get_run(self, run_id: int) -> Optional[Run]:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return self._row_to_run(row) if row else None

    def latest_run_id(self) -> Optional[int]:
        row = self._conn.execute(
            "SELECT id FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else None

    # --- items --------------------------------------------------------------

    def upsert_item(
        self,
        run_id: int,
        key: str,
        stage: str = "",
        *,
        status: ItemStatus = ItemStatus.OK,
        bump_attempts: bool = True,
    ) -> int:
        now = utc_now_iso()
        with self._transaction() as conn:
            existing = conn.execute(
                """
                SELECT id, attempts, status FROM items
                WHERE run_id = ? AND key = ? AND stage = ?
                """,
                (run_id, key, stage),
            ).fetchone()
            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO items(
                        run_id, key, stage, status, attempts, started_at, ended_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, key, stage, status.value, 1 if bump_attempts else 0, now, now),
                )
                return int(cur.lastrowid)

            attempts = int(existing["attempts"]) + (1 if bump_attempts else 0)
            final_status = status
            if (
                status == ItemStatus.OK
                and attempts > 1
                and existing["status"] == ItemStatus.FAILED.value
            ):
                final_status = ItemStatus.RETRIED

            conn.execute(
                """
                UPDATE items
                SET status = ?, attempts = ?, ended_at = ?
                WHERE id = ?
                """,
                (final_status.value, attempts, now, int(existing["id"])),
            )
            return int(existing["id"])

    def get_item(self, item_id: int) -> Optional[Item]:
        row = self._conn.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return self._row_to_item(row) if row else None

    # --- errors -------------------------------------------------------------

    def insert_errors(self, errors: Sequence[NewError]) -> List[int]:
        """Insert error nodes; returns assigned ids in input order."""
        if not errors:
            return []
        ids: List[int] = []
        # Map temporary negative parent refs if needed — parents must already
        # be in the list ahead of children (capture layer guarantees this).
        index_to_id: Dict[int, int] = {}
        with self._transaction() as conn:
            for idx, err in enumerate(errors):
                parent_id = err.parent_error_id
                if parent_id is not None and parent_id < 0:
                    # Convention: parent_error_id = -(index+1) of prior node
                    parent_id = index_to_id[(-parent_id) - 1]
                cur = conn.execute(
                    """
                    INSERT INTO errors(
                        item_id, parent_error_id, depth, exc_type, message,
                        normalized_message, traceback, fingerprint, ts, is_group_root
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        err.item_id,
                        parent_id,
                        err.depth,
                        err.exc_type,
                        err.message,
                        err.normalized_message,
                        err.traceback,
                        err.fingerprint,
                        err.ts,
                        1 if err.is_group_root else 0,
                    ),
                )
                new_id = int(cur.lastrowid)
                index_to_id[idx] = new_id
                ids.append(new_id)
        return ids

    def get_error(self, error_id: int) -> Optional[ErrorRecord]:
        row = self._conn.execute(
            "SELECT * FROM errors WHERE id = ?", (error_id,)
        ).fetchone()
        return self._row_to_error(row) if row else None

    def list_child_errors(self, parent_error_id: int) -> List[ErrorRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM errors
            WHERE parent_error_id = ?
            ORDER BY id
            """,
            (parent_error_id,),
        ).fetchall()
        return [self._row_to_error(r) for r in rows]

    # --- groups (GroupStore protocol) ---------------------------------------

    def bump_group(
        self,
        *,
        fingerprint: str,
        title: str,
        error_id: int,
        ts: Optional[str] = None,
        sample_cap: int = 5,
    ) -> None:
        """Atomically insert or increment a group and attach an example id."""
        now = ts or utc_now_iso()
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM groups WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO groups(
                        fingerprint, title, count, first_seen, last_seen, example_ids
                    )
                    VALUES (?, ?, 1, ?, ?, ?)
                    """,
                    (
                        fingerprint,
                        title,
                        now,
                        now,
                        dumps_json(append_example_id([], error_id, sample_cap=sample_cap)),
                    ),
                )
                return

            examples = loads_json(row["example_ids"], default=[])
            if not isinstance(examples, list):
                examples = []
            examples = append_example_id(examples, error_id, sample_cap=sample_cap)
            conn.execute(
                """
                UPDATE groups
                SET count = count + 1,
                    last_seen = ?,
                    example_ids = ?
                WHERE fingerprint = ?
                """,
                (now, dumps_json(examples), fingerprint),
            )

    def get_group(self, fingerprint: str) -> Optional[Group]:
        row = self._conn.execute(
            "SELECT * FROM groups WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return self._dict_to_group(dict(row)) if row else None

    def list_groups(self, *, limit: int = 100, offset: int = 0) -> List[Group]:
        rows = self._conn.execute(
            """
            SELECT * FROM groups
            ORDER BY count DESC, last_seen DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [self._dict_to_group(dict(r)) for r in rows]

    # --- summary / export queries -------------------------------------------

    def get_summary(self, run_id: int) -> RunSummary:
        rows = self._conn.execute(
            """
            SELECT status, COUNT(*) AS n,
                   SUM(CASE WHEN attempts > 1 AND status IN ('ok', 'retried')
                            THEN 1 ELSE 0 END) AS recovered
            FROM items
            WHERE run_id = ?
            GROUP BY status
            """,
            (run_id,),
        ).fetchall()
        counts = {r["status"]: int(r["n"]) for r in rows}
        recovered = sum(int(r["recovered"] or 0) for r in rows)
        groups_row = self._conn.execute(
            """
            SELECT COUNT(DISTINCT e.fingerprint) AS n
            FROM errors e
            JOIN items i ON i.id = e.item_id
            WHERE i.run_id = ? AND e.is_group_root = 1
            """,
            (run_id,),
        ).fetchone()
        total = sum(counts.values())
        return RunSummary(
            run_id=run_id,
            total=total,
            ok=counts.get(ItemStatus.OK.value, 0)
            + counts.get(ItemStatus.RETRIED.value, 0),
            failed=counts.get(ItemStatus.FAILED.value, 0),
            skipped=counts.get(ItemStatus.SKIPPED.value, 0),
            recovered=recovered,
            groups=int(groups_row["n"] if groups_row else 0),
        )

    def iter_failed_keys(
        self,
        run_id: int,
        *,
        exc_type: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> List[str]:
        sql = """
            SELECT DISTINCT i.key
            FROM items i
            LEFT JOIN errors e ON e.item_id = i.id AND e.is_group_root = 1
            WHERE i.run_id = ? AND i.status = ?
        """
        params: List[Any] = [run_id, ItemStatus.FAILED.value]
        if stage is not None:
            sql += " AND i.stage = ?"
            params.append(stage)
        if exc_type is not None:
            sql += " AND e.exc_type = ?"
            params.append(exc_type)
        sql += " ORDER BY i.key"
        rows = self._conn.execute(sql, params).fetchall()
        return [str(r["key"]) for r in rows]

    # --- mappers ------------------------------------------------------------

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> Run:
        return Run(
            id=int(row["id"]),
            label=row["label"],
            started_at=parse_iso(row["started_at"]),
            ended_at=parse_iso(row["ended_at"]) if row["ended_at"] else None,
            status=RunStatus(row["status"]),
            meta=loads_json(row["meta_json"], default={}) or {},
        )

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> Item:
        return Item(
            id=int(row["id"]),
            run_id=int(row["run_id"]),
            key=row["key"],
            stage=row["stage"],
            status=ItemStatus(row["status"]),
            attempts=int(row["attempts"]),
        )

    @staticmethod
    def _row_to_error(row: sqlite3.Row) -> ErrorRecord:
        return ErrorRecord(
            id=int(row["id"]),
            item_id=int(row["item_id"]),
            parent_error_id=(
                int(row["parent_error_id"]) if row["parent_error_id"] is not None else None
            ),
            depth=int(row["depth"]),
            exc_type=row["exc_type"],
            message=row["message"],
            normalized_message=row["normalized_message"],
            traceback=row["traceback"],
            fingerprint=row["fingerprint"],
            ts=parse_iso(row["ts"]),
            is_group_root=bool(row["is_group_root"]),
        )

    @staticmethod
    def _dict_to_group(row: Dict[str, Any]) -> Group:
        examples = loads_json(row["example_ids"], default=[])
        if not isinstance(examples, list):
            examples = []
        return Group(
            fingerprint=row["fingerprint"],
            title=row["title"],
            count=int(row["count"]),
            first_seen=parse_iso(row["first_seen"]),
            last_seen=parse_iso(row["last_seen"]),
            example_ids=tuple(int(x) for x in examples),
        )
