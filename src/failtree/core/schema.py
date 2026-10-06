"""SQLite DDL and schema versioning (Single Responsibility: structure only)."""

from __future__ import annotations

SCHEMA_VERSION = 1

PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA foreign_keys=ON;",
    "PRAGMA busy_timeout=5000;",
    "PRAGMA temp_store=MEMORY;",
)

DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    label       TEXT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    status      TEXT NOT NULL DEFAULT 'running',
    meta_json   TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    stage       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    started_at  TEXT,
    ended_at    TEXT,
    UNIQUE(run_id, key, stage)
);

CREATE TABLE IF NOT EXISTS errors (
    id                 INTEGER PRIMARY KEY,
    item_id            INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    parent_error_id    INTEGER REFERENCES errors(id) ON DELETE CASCADE,
    depth              INTEGER NOT NULL DEFAULT 0,
    exc_type           TEXT NOT NULL,
    message            TEXT NOT NULL,
    normalized_message TEXT NOT NULL,
    traceback          TEXT NOT NULL,
    fingerprint        TEXT NOT NULL,
    ts                 TEXT NOT NULL,
    is_group_root      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS groups (
    fingerprint   TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    count         INTEGER NOT NULL DEFAULT 0,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    example_ids   TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_items_run_status ON items(run_id, status);
CREATE INDEX IF NOT EXISTS idx_items_run_stage  ON items(run_id, stage);
CREATE INDEX IF NOT EXISTS idx_errors_item      ON errors(item_id);
CREATE INDEX IF NOT EXISTS idx_errors_fp        ON errors(fingerprint);
CREATE INDEX IF NOT EXISTS idx_errors_parent    ON errors(parent_error_id);
"""
