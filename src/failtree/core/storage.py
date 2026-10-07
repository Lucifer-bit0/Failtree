"""SQLite persistence for runs, items, errors, and groups."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from failtree.common.jsonutil import dumps_json, loads_json
from failtree.common.timeutil import parse_iso, utc_now_iso
from failtree.core.grouping import append_example_id
from failtree.core.models import (
    ErrorRecord,
    Gate,
    Group,
    GroupImpact,
    Item,
    ItemStatus,
    NewError,
    Run,
    RunFile,
    RunStatus,
    RunSummary,
)
from failtree.core.schema import DDL, MIGRATIONS, PRAGMAS, SCHEMA_VERSION


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
                return

            current = int(row["version"])
            if current == SCHEMA_VERSION:
                return
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {current} is newer than "
                    f"supported {SCHEMA_VERSION}"
                )
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for stmt in MIGRATIONS.get(version, ()):
                    try:
                        self._conn.execute(stmt)
                    except sqlite3.OperationalError as exc:
                        # Column may already exist on partially migrated DBs.
                        if "duplicate column" not in str(exc).lower():
                            raise
                self._conn.execute(
                    "UPDATE schema_version SET version = ?", (version,)
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
        *,
        code_version: Optional[str] = None,
        code_version_source: Optional[str] = None,
    ) -> int:
        started = utc_now_iso()
        meta_data = dict(meta or {})
        if code_version and "code_version" not in meta_data:
            meta_data["code_version"] = code_version
            meta_data["code_version_source"] = code_version_source
        meta_json = dumps_json(meta_data)
        with self._transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs(
                    label, started_at, status, meta_json, heartbeat_at,
                    code_version, code_version_source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    label,
                    started,
                    RunStatus.RUNNING.value,
                    meta_json,
                    started,
                    code_version,
                    code_version_source,
                ),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: RunStatus = RunStatus.COMPLETED) -> None:
        with self._transaction() as conn:
            conn.execute(
                """
                UPDATE runs
                SET ended_at = ?, status = ?, heartbeat_at = ?
                WHERE id = ?
                """,
                (utc_now_iso(), status.value, utc_now_iso(), run_id),
            )

    def heartbeat(self, run_id: int) -> None:
        """Touch last-seen timestamp so viewers can detect stalled runs."""
        with self._transaction() as conn:
            conn.execute(
                "UPDATE runs SET heartbeat_at = ? WHERE id = ?",
                (utc_now_iso(), run_id),
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

    def ensure_item(self, run_id: int, key: str, stage: str = "") -> int:
        """Get or create an item without bumping attempts or finalizing status."""
        now = utc_now_iso()
        with self._transaction() as conn:
            existing = conn.execute(
                """
                SELECT id FROM items
                WHERE run_id = ? AND key = ? AND stage = ?
                """,
                (run_id, key, stage),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO items(
                    run_id, key, stage, status, attempts, started_at, ended_at
                )
                VALUES (?, ?, ?, ?, 0, ?, NULL)
                """,
                (run_id, key, stage, ItemStatus.OK.value, now),
            )
            return int(cur.lastrowid)

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
                        normalized_message, traceback, fingerprint, ts,
                        is_group_root, gate
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        err.gate,
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

    def list_errors_for_item(self, item_id: int) -> List[ErrorRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM errors
            WHERE item_id = ?
            ORDER BY id
            """,
            (item_id,),
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

    def list_groups(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        query: Optional[str] = None,
    ) -> List[Group]:
        if query:
            like = f"%{query}%"
            rows = self._conn.execute(
                """
                SELECT * FROM groups
                WHERE title LIKE ? OR fingerprint LIKE ?
                ORDER BY count DESC, last_seen DESC
                LIMIT ? OFFSET ?
                """,
                (like, like, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM groups
                ORDER BY count DESC, last_seen DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._dict_to_group(dict(r)) for r in rows]

    def list_items_for_group(
        self,
        fingerprint: str,
        *,
        run_id: Optional[int] = None,
        stage: Optional[str] = None,
        limit: int = 200,
    ) -> List[Item]:
        sql = """
            SELECT DISTINCT i.*
            FROM items i
            JOIN errors e ON e.item_id = i.id
            WHERE e.fingerprint = ? AND e.is_group_root = 1
        """
        params: List[Any] = [fingerprint]
        if run_id is not None:
            sql += " AND i.run_id = ?"
            params.append(run_id)
        if stage is not None:
            sql += " AND i.stage = ?"
            params.append(stage)
        sql += " ORDER BY i.id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list_root_errors_for_item(self, item_id: int) -> List[ErrorRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM errors
            WHERE item_id = ? AND parent_error_id IS NULL
            ORDER BY id
            """,
            (item_id,),
        ).fetchall()
        return [self._row_to_error(r) for r in rows]

    def list_runs(self, *, limit: int = 50) -> List[Run]:
        rows = self._conn.execute(
            """
            SELECT * FROM runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_run(r) for r in rows]

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
            ok=counts.get(ItemStatus.OK.value, 0),
            failed=counts.get(ItemStatus.FAILED.value, 0),
            skipped=counts.get(ItemStatus.SKIPPED.value, 0),
            retried=counts.get(ItemStatus.RETRIED.value, 0),
            recovered=recovered,
            groups=int(groups_row["n"] if groups_row else 0),
        )

    def rank_groups(
        self,
        run_id: int,
        *,
        limit: int = 20,
    ) -> List[GroupImpact]:
        """Rank root-cause groups by share of failed items in a run."""
        failed_row = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM items
            WHERE run_id = ? AND status = ?
            """,
            (run_id, ItemStatus.FAILED.value),
        ).fetchone()
        failed_total = int(failed_row["n"] if failed_row else 0)
        if failed_total == 0:
            return []

        rows = self._conn.execute(
            """
            SELECT e.fingerprint AS fingerprint,
                   g.title AS title,
                   g.count AS global_count,
                   COUNT(DISTINCT i.id) AS failed_items
            FROM errors e
            JOIN items i ON i.id = e.item_id
            LEFT JOIN groups g ON g.fingerprint = e.fingerprint
            WHERE i.run_id = ?
              AND i.status = ?
              AND e.is_group_root = 1
            GROUP BY e.fingerprint
            ORDER BY failed_items DESC, e.fingerprint
            LIMIT ?
            """,
            (run_id, ItemStatus.FAILED.value, limit),
        ).fetchall()

        impacts: List[GroupImpact] = []
        for row in rows:
            failed_items = int(row["failed_items"])
            title = row["title"] or row["fingerprint"]
            impacts.append(
                GroupImpact(
                    fingerprint=row["fingerprint"],
                    title=title,
                    count=int(row["global_count"] or failed_items),
                    failed_items=failed_items,
                    pct_of_failures=round(100.0 * failed_items / failed_total, 1),
                )
            )
        return impacts

    def fingerprint_counts_for_run(self, run_id: int) -> Dict[str, Dict[str, Any]]:
        """Map fingerprint → {count, title} for failed group-root errors in a run.

        ``count`` is the number of distinct failed items with that fingerprint.
        """
        rows = self._conn.execute(
            """
            SELECT e.fingerprint AS fingerprint,
                   g.title AS title,
                   COUNT(DISTINCT i.id) AS failed_items
            FROM errors e
            JOIN items i ON i.id = e.item_id
            LEFT JOIN groups g ON g.fingerprint = e.fingerprint
            WHERE i.run_id = ?
              AND i.status = ?
              AND e.is_group_root = 1
            GROUP BY e.fingerprint
            """,
            (run_id, ItemStatus.FAILED.value),
        ).fetchall()
        return {
            str(row["fingerprint"]): {
                "count": int(row["failed_items"]),
                "title": str(row["title"] or row["fingerprint"]),
            }
            for row in rows
        }

    def snapshot_run_file(
        self,
        run_id: int,
        path: str,
        content_hash: str,
        content: str,
    ) -> None:
        """Store a deduplicated source snapshot for a run."""
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO code_blobs(content_hash, content)
                VALUES (?, ?)
                """,
                (content_hash, content),
            )
            conn.execute(
                """
                INSERT INTO run_files(run_id, path, content_hash)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id, path) DO UPDATE SET
                    content_hash = excluded.content_hash
                """,
                (run_id, path, content_hash),
            )

    def list_run_files(self, run_id: int) -> List[RunFile]:
        rows = self._conn.execute(
            """
            SELECT run_id, path, content_hash
            FROM run_files
            WHERE run_id = ?
            ORDER BY path
            """,
            (run_id,),
        ).fetchall()
        return [
            RunFile(
                run_id=int(r["run_id"]),
                path=str(r["path"]),
                content_hash=str(r["content_hash"]),
            )
            for r in rows
        ]

    def get_code_blob(self, content_hash: Optional[str]) -> Optional[str]:
        if not content_hash:
            return None
        row = self._conn.execute(
            "SELECT content FROM code_blobs WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return str(row["content"]) if row else None

    def list_frame_hints_for_run(
        self,
        run_id: int,
        *,
        fingerprint: Optional[str] = None,
    ) -> List[tuple[str, str, bool]]:
        """Parse traceback frames from errors: (path, func, is_group_root)."""
        import re

        sql = """
            SELECT e.traceback AS traceback, e.is_group_root AS is_group_root
            FROM errors e
            JOIN items i ON i.id = e.item_id
            WHERE i.run_id = ?
        """
        params: List[Any] = [run_id]
        if fingerprint is not None:
            sql += " AND e.fingerprint = ?"
            params.append(fingerprint)
        rows = self._conn.execute(sql, params).fetchall()
        frame_re = re.compile(
            r'File "([^"]+)", line \d+, in (\S+)'
        )
        out: List[tuple[str, str, bool]] = []
        seen: set[tuple[str, str, bool]] = set()
        for row in rows:
            tb = row["traceback"] or ""
            is_root = bool(row["is_group_root"])
            for match in frame_re.finditer(tb):
                key = (match.group(1), match.group(2), is_root)
                if key in seen:
                    continue
                seen.add(key)
                out.append(key)
        # Prefer root-cause hints first for callers that iterate in order.
        out.sort(key=lambda t: (0 if t[2] else 1, t[0], t[1]))
        return out

    def iter_failed_keys(
        self,
        run_id: int,
        *,
        exc_type: Optional[str] = None,
        stage: Optional[str] = None,
        fingerprint: Optional[str] = None,
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
        if fingerprint is not None:
            sql += " AND e.fingerprint = ?"
            params.append(fingerprint)
        sql += " ORDER BY i.key"
        rows = self._conn.execute(sql, params).fetchall()
        return [str(r["key"]) for r in rows]

    # --- mappers ------------------------------------------------------------

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> Run:
        code_version = None
        code_version_source = None
        try:
            code_version = row["code_version"]
            code_version_source = row["code_version_source"]
        except (IndexError, KeyError):
            pass
        return Run(
            id=int(row["id"]),
            label=row["label"],
            started_at=parse_iso(row["started_at"]),
            ended_at=parse_iso(row["ended_at"]) if row["ended_at"] else None,
            status=RunStatus(row["status"]),
            meta=loads_json(row["meta_json"], default={}) or {},
            code_version=code_version,
            code_version_source=code_version_source,
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
        gate_raw = None
        try:
            gate_raw = row["gate"]
        except (IndexError, KeyError):
            gate_raw = None
        gate = Gate(gate_raw) if gate_raw in (Gate.OR.value, Gate.AND.value) else None
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
            gate=gate,
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
