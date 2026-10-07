# failtree — Event schema (P0)

This document defines what one captured failure contains and how events flow through the **sink** interface.

## Entities

### Run
One pipeline / process execution.

| Field | Type | Notes |
|-------|------|--------|
| `id` | int | Primary key |
| `label` | str \| null | Service or job name |
| `started_at` | ISO-8601 UTC | |
| `ended_at` | ISO-8601 UTC \| null | |
| `status` | `running` \| `completed` \| `aborted` | |
| `heartbeat_at` | ISO-8601 UTC \| null | Last alive signal |
| `meta` | object | Opaque JSON (git sha, env, host, …) |

### Item
One unit of work (file, batch id, boot key, …).

| Field | Type | Notes |
|-------|------|--------|
| `id` | int | |
| `run_id` | int | FK → runs |
| `key` | str | Stable identity (filename, well id, `__main__`) |
| `stage` | str | e.g. `parse`, `download`, `boot` |
| `status` | `ok` \| `failed` \| `retried` \| `skipped` | |
| `attempts` | int | |
| `started_at` / `ended_at` | ISO-8601 \| null | |

Unique: `(run_id, key, stage)`.

### Error (node)
One exception node in a causality tree.

| Field | Type | Notes |
|-------|------|--------|
| `id` | int | |
| `item_id` | int | FK → items |
| `parent_error_id` | int \| null | Parent in cause/context/group tree |
| `depth` | int | 0 = root |
| `exc_type` | str | e.g. `ValueError` |
| `message` | str | Raw (after optional redaction) |
| `normalized_message` | str | Fingerprint input |
| `traceback` | str | Formatted traceback (after optional redaction) |
| `fingerprint` | str | Short hash for grouping |
| `ts` | ISO-8601 | |
| `is_group_root` | bool | Leaf used for group counts |

### Group
Root-cause cluster keyed by fingerprint.

| Field | Type | Notes |
|-------|------|--------|
| `fingerprint` | str | PK |
| `title` | str | Human-readable |
| `count` | int | |
| `first_seen` / `last_seen` | ISO-8601 | |
| `example_ids` | int[] | Capped sample of error ids |

## Capture → sink events

Capture emits logical operations; sinks persist them.

| Operation | Meaning |
|-----------|---------|
| `start_run` | Create a run row |
| `finish_run` | Set ended_at + status |
| `heartbeat` | Touch `heartbeat_at` |
| `ensure_item` | Get/create item |
| `finalize_item` | Set status / attempts |
| `insert_errors` | Persist error tree nodes |
| `bump_group` | Increment group + examples |
| `close` | Release resources |

## Sink interface

See `failtree.core.sink.ErrorSink`.

- **v1:** `SqliteSink` → local WAL database  
- **later:** `HttpSink` → multi-service server (same operations over HTTP)

Capture (`Tracker`, hooks, `run` / `run_command`) depends only on `ErrorSink`, not on SQLite types.
