from __future__ import annotations

import sqlite3
from pathlib import Path

from failtree.core.schema import SCHEMA_VERSION
from failtree.core.sink import SqliteSink
from failtree.core.storage import Storage


def test_sqlite_sink_start_and_heartbeat(tmp_path: Path) -> None:
    sink = SqliteSink(tmp_path / "runs.db")
    run_id = sink.start_run(label="p0")
    sink.heartbeat(run_id)
    row = sink.storage._conn.execute(  # noqa: SLF001
        "SELECT heartbeat_at, status FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert row["heartbeat_at"]
    assert row["status"] == "running"
    sink.close()


def test_migrate_v1_to_v2(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version(version) VALUES (1);
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY,
            label TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            meta_json TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            started_at TEXT,
            ended_at TEXT,
            UNIQUE(run_id, key, stage)
        );
        CREATE TABLE errors (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL,
            parent_error_id INTEGER,
            depth INTEGER NOT NULL DEFAULT 0,
            exc_type TEXT NOT NULL,
            message TEXT NOT NULL,
            normalized_message TEXT NOT NULL,
            traceback TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            ts TEXT NOT NULL,
            is_group_root INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE groups (
            fingerprint TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            example_ids TEXT NOT NULL DEFAULT '[]'
        );
        """
    )
    conn.close()

    with Storage(db) as store:
        ver = store._conn.execute(  # noqa: SLF001
            "SELECT version FROM schema_version"
        ).fetchone()[0]
        assert ver == SCHEMA_VERSION
        cols = {
            r[1]
            for r in store._conn.execute("PRAGMA table_info(runs)").fetchall()  # noqa: SLF001
        }
        assert "heartbeat_at" in cols
