# failtree — Low-Level Design (LLD)

Companion to [HLD.md](./HLD.md). This document is detailed enough to implement from.

Working package name: `failtree`.

---

## 1. Repository layout

```
failtree/
  pyproject.toml
  README.md
  LICENSE
  CONTRIBUTING.md
  src/failtree/
    __init__.py          # export Tracker, version
    cli.py               # argparse/typer entry
    core/
      __init__.py
      models.py          # dataclasses / TypedDicts
      storage.py         # SQLite access
      fingerprint.py     # normalize + hash
      grouping.py        # group upsert / examples
      summary.py         # aggregations
      export.py          # retry list writers
    capture/
      __init__.py
      tracker.py         # Tracker, item(), decorator
      chains.py          # exception graph walk
      concurrency.py     # locks, busy retry helpers
    viewer/
      __init__.py
      app.py             # Textual App
      widgets.py         # tree, detail, header
      loading.py         # lazy data providers
  tests/
    core/
    capture/
    viewer/              # Textual pilot tests (optional early)
    fixtures/
      messy_errors.json  # golden fingerprint cases
  examples/
    fake_pipeline.py
  docs/
    ARCHITECTURE.md
    HLD.md
    LLD.md
    ROADMAP.md
```

---

## 2. Data model (SQLite)

### 2.1 Pragmas (on connect)

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;   -- ms; tune under stress
PRAGMA temp_store=MEMORY;
```

### 2.2 Schema

```sql
CREATE TABLE runs (
    id          INTEGER PRIMARY KEY,
    label       TEXT,
    started_at  TEXT NOT NULL,          -- ISO-8601 UTC
    ended_at    TEXT,
    status      TEXT NOT NULL DEFAULT 'running',  -- running|completed|aborted
    meta_json   TEXT                    -- optional opaque JSON
);

CREATE TABLE items (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,          -- filename, batch id, etc.
    stage       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,          -- ok|failed|retried|skipped
    attempts    INTEGER NOT NULL DEFAULT 0,
    started_at  TEXT,
    ended_at    TEXT,
    UNIQUE(run_id, key, stage)
);

CREATE TABLE errors (
    id               INTEGER PRIMARY KEY,
    item_id          INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    parent_error_id  INTEGER REFERENCES errors(id) ON DELETE CASCADE,
    depth            INTEGER NOT NULL DEFAULT 0,
    exc_type         TEXT NOT NULL,
    message          TEXT NOT NULL,
    normalized_message TEXT NOT NULL,
    traceback        TEXT NOT NULL,
    fingerprint      TEXT NOT NULL,
    ts               TEXT NOT NULL,
    is_group_root    INTEGER NOT NULL DEFAULT 0  -- 1 if used for grouping
);

CREATE TABLE groups (
    fingerprint   TEXT PRIMARY KEY,
    title         TEXT NOT NULL,        -- human-readable, e.g. "ValueError: invalid ..."
    count         INTEGER NOT NULL DEFAULT 0,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    example_ids   TEXT NOT NULL DEFAULT '[]'  -- JSON array of error ids, capped
);

CREATE INDEX idx_items_run_status ON items(run_id, status);
CREATE INDEX idx_items_run_stage  ON items(run_id, stage);
CREATE INDEX idx_errors_item      ON errors(item_id);
CREATE INDEX idx_errors_fp        ON errors(fingerprint);
CREATE INDEX idx_errors_parent    ON errors(parent_error_id);
```

### 2.3 Status semantics

| Status | Meaning |
|--------|---------|
| `ok` | Latest attempt succeeded |
| `failed` | Latest attempt raised; not succeeded since |
| `retried` | Had ≥1 failure earlier in this run, later succeeded (optional; or keep `ok` + `attempts>1`) |
| `skipped` | Explicitly skipped by user API |

**Recommendation for v1:**  
- On success: `status=ok`, increment `attempts`.  
- On failure: `status=failed`, increment `attempts`.  
- Summary can report `recovered = attempts>1 AND status=ok` without a separate `retried` status.  
- Keep `retried` in the enum if you want it visible in filters; set when success follows prior fail on same `(run_id,key,stage)`.

### 2.4 In-memory models (`core/models.py`)

```python
@dataclass(frozen=True)
class Run:
    id: int
    label: str | None
    started_at: datetime
    ended_at: datetime | None
    status: str
    meta: dict[str, Any]

@dataclass(frozen=True)
class Item:
    id: int
    run_id: int
    key: str
    stage: str
    status: str
    attempts: int

@dataclass(frozen=True)
class ErrorNode:
    id: int
    item_id: int
    parent_error_id: int | None
    depth: int
    exc_type: str
    message: str
    normalized_message: str
    traceback: str
    fingerprint: str
    ts: datetime

@dataclass(frozen=True)
class Group:
    fingerprint: str
    title: str
    count: int
    first_seen: datetime
    last_seen: datetime
    example_ids: list[int]

@dataclass(frozen=True)
class RunSummary:
    run_id: int
    total: int
    ok: int
    failed: int
    skipped: int
    recovered: int          # ok with attempts > 1
    groups: int
    progress_per_sec: float | None
```

---

## 3. Module designs

### 3.1 `core/storage.py`

**Class: `Storage`**

| Method | Behavior |
|--------|----------|
| `Storage(path: Path)` | Connect, apply pragmas, migrate schema |
| `create_run(label, meta) -> int` | Insert run |
| `finish_run(run_id, status)` | Set `ended_at`, status |
| `upsert_item(...)` | Insert or update by `(run_id,key,stage)` |
| `insert_errors(nodes: list[NewError])` | Transactional batch insert |
| `bump_group(fp, title, error_id, ts, sample_cap=5)` | Upsert count + ring of examples |
| `get_summary(run_id) -> RunSummary` | Aggregates |
| `list_groups(run_id=None, limit, offset)` | For TUI/CLI |
| `list_items_for_group(fp, run_id)` | Lazy expand |
| `get_error_tree(root_error_id)` | Children by `parent_error_id` |
| `iter_failed_keys(run_id, *, exc_type, stage)` | Export |

**Migration:** simple `schema_version` table; v1 = version 1. No Alembic required initially.

**Connection policy:**

- One `Storage` instance per process preferred.  
- `threading.RLock` around write transactions.  
- On `sqlite3.OperationalError` with busy/locked: exponential backoff retry (see `capture/concurrency.py`).

### 3.2 `core/fingerprint.py`

**Inputs:** exception type name, message, traceback frames, `project_roots: list[Path]`.

**Algorithm:**

1. **Normalize message**
   - Lowercase optional? **No** — preserve type case; normalize only volatile tokens.
   - Replace in order (regex):
     - UUIDs → `<UUID>`
     - ISO timestamps → `<TS>`
     - Integers / floats → `<NUM>`
     - Absolute/relative file paths → `<PATH>`
     - Quoted strings `'...'` / `"..."` → `<STR>` (optional; may over-group — make configurable)
     - Hex hashes `\b[a-f0-9]{7,}\b` → `<HEX>`
   - Collapse whitespace.

2. **Select frames**
   - Parse traceback into frames `(file, func, line)`.
   - Keep frames under `project_roots` (or not in site-packages/stdlib).
   - Take top **N=3** deepest in-project frames (closest to throw site).
   - Use `func` + basename(`file`) — **ignore line numbers**.

3. **Fingerprint string**
   ```
   f"{exc_type}|{normalized_message}|{'<'+ '>'.join(f'{file}:{func}' for ...)}"
   ```

4. **Hash**
   - `sha256(fingerprint_string.encode()).hexdigest()[:16]`  
   - Store both short hash (DB key) and keep `title` from type + truncated normalized message.

**Config object:**

```python
@dataclass
class FingerprintConfig:
    project_roots: tuple[Path, ...] = ()
    top_frames: int = 3
    strip_quoted_strings: bool = True
    extra_patterns: tuple[tuple[str, str], ...] = ()  # (regex, repl)
```

**Grouping node selection:** fingerprint the **leaf** (deepest cause) by default; store fingerprints on all nodes but set `is_group_root=1` only on the leaf used for group counts. Document this choice; allow config `group_on: leaf|root`.

### 3.3 `core/grouping.py`

```python
def upsert_group(storage, *, fingerprint, title, error_id, ts, sample_cap=5):
    # INSERT ... ON CONFLICT DO UPDATE
    # count = count + 1
    # last_seen = ts
    # example_ids = append error_id if len < sample_cap
```

Title: `f"{exc_type}: {normalized_message[:120]}"`.

### 3.4 `capture/chains.py`

**Function: `walk_exception(exc: BaseException, *, max_depth=16) -> list[ChainNode]`**

```python
@dataclass
class ChainNode:
    exc: BaseException
    parent_index: int | None   # index in result list
    depth: int
    relation: str              # cause|context|group_child|root
```

**Rules:**

1. BFS/DFS from root exception; assign indices.  
2. Follow `__cause__` (explicit) preferentially; also `__context__` if different and not suppressed (`__suppress_context__`).  
3. If `ExceptionGroup` / `BaseExceptionGroup` (use `exceptiongroup` backport): expand `.exceptions` as children with `relation=group_child`.  
4. Cycle guard: `id(exc)` set.  
5. Stop at `max_depth`.  
6. Produce traceback text via `traceback` module per node.

**Never raise** from walker; on formatting failure store `traceback="<unavailable>"`.

### 3.5 `capture/tracker.py`

```python
class Tracker:
    def __init__(
        self,
        db_path: str | Path,
        *,
        label: str | None = None,
        project_roots: Sequence[str | Path] | None = None,
        continue_on_error: bool = False,
        fingerprint_config: FingerprintConfig | None = None,
    ): ...

    def item(self, key: str, *, stage: str = "") -> Iterator[ItemHandle]: ...
    def track(self, *, stage: str = "", key_arg: str | int | None = None):  # decorator
        ...
    def summary(self) -> RunSummary: ...
    def close(self) -> None: ...  # finish run if still open

    def __enter__/__exit__  # optional: run lifespan
```

**`item()` context manager:**

```python
@contextmanager
def item(self, key, *, stage=""):
    item_id = self.storage.upsert_item(... status pending/start ...)
    try:
        yield ItemHandle(item_id, key, stage)
        self.storage.mark_ok(item_id)
    except BaseException as exc:
        nodes = walk_exception(exc)
        persisted = self._persist_chain(item_id, nodes)
        self.storage.mark_failed(item_id)
        if self.continue_on_error:
            return  # suppress
        raise
```

**Decorator:**

```python
@t.track(stage="parse")
def process(path): ...
# key default: str(first arg) or kwargs['key']
```

**Public export in `__init__.py`:** `Tracker` only (keep surface tiny).

### 3.6 `capture/concurrency.py`

```python
def write_with_retry(fn, *, retries=10, base_delay=0.01):
    for attempt in range(retries):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            time.sleep(base_delay * (2 ** attempt) * jitter())
    raise
```

v1.x: `WriterThread` with `queue.Queue` of write ops for multiprocess via a dedicated writer process (optional advanced API).

### 3.7 `core/summary.py` / `core/export.py`

**Summary SQL (sketch):**

```sql
SELECT status, COUNT(*), SUM(CASE WHEN attempts > 1 AND status='ok' THEN 1 ELSE 0 END)
FROM items WHERE run_id = ?
GROUP BY status;
```

**Export:**

```python
def export_failed_keys(storage, run_id, *, exc_type: str | None, stage: str | None, dest: Path):
    # DISTINCT items.key WHERE status=failed AND optional joins to errors.exc_type
```

CLI:

```text
failtree summary runs.db [--run ID]
failtree view runs.db [--run ID]
failtree export runs.db --failed-type ValueError [--stage parse] -o retry.txt
```

### 3.8 Viewer (`viewer/app.py`, `widgets.py`)

**Layout:**

```
┌──────────────────────────────────────────────────────────┐
│ Header: run label · ok/failed/recovered · rate · refresh │
├────────────────────────────┬─────────────────────────────┤
│ Tree                       │ Detail                      │
│ > Group (count)            │ type, message, fingerprint  │
│    > item key @ stage      │ traceback (scroll)          │
│       > error (+children)  │ timestamps, item meta       │
└────────────────────────────┴─────────────────────────────┘
```
**Keybindings:**

| Key | Action |
|-----|--------|
| `/` | Search groups/items |
| `f` | Filter stage/status |
| `e` | Export retry list (filtered) |
| `r` | Refresh now |
| `q` | Quit |

**Lazy loading:**  
- Level 0: groups query `LIMIT`.  
- On expand group: items for fingerprint.  
- On expand item: error roots; on expand error: children where `parent_error_id=?`.

**Refresh:** `set_interval(2.0, refresh_header_and_dirty_nodes)`.

**Dependency isolation:** `viewer` imported only from `cli view` when Textual installed; else clear error “pip install failtree[tui]”.

---

## 4. Sequence diagrams

### 4.1 Failed item capture

```
Pipeline          Tracker          ChainWalker       Fingerprinter       Storage
   |                |                  |                  |                 |
   | item(key)      |                  |                  |                 |
   |--------------->| upsert item      |                  |                 |
   |                |------------------------------------>|                 |
   | process() raises                  |                  |                 |
   |--------------->| walk(exc)        |                  |                 |
   |                |----------------->|                  |                 |
   |                | nodes[]          |                  |                 |
   |                |-----------------fingerprint each-->|                 |
   |                | insert_errors + bump_group ---------------------------->|
   |                | mark failed                                            |
   | re-raise       |                  |                  |                 |
   |<---------------|                  |                  |                 |
```

### 4.2 TUI expand group

```
User   TuiApp   Storage
  |      |         |
  | expand group   |
  |----->| list_items_for_group(fp)
  |      |-------->|
  |      | rows    |
  |      |-- render children
```

---

## 5. Fingerprint golden fixtures

File: `tests/fixtures/messy_errors.json`

Each case:

```json
{
  "id": "uuid-stripped",
  "exc_type": "ValueError",
  "message": "bad id 550e8400-e29b-41d4-a716-446655440000",
  "frames": [
    {"file": "/proj/pipeline/parse.py", "func": "parse_row", "line": 10},
    {"file": "/usr/lib/python3.11/json/__init__.py", "func": "loads", "line": 1}
  ],
  "expect_group": "G1"
}
```

Cases that must share `expect_group`:

- Same bug, different UUIDs / paths / numbers  
- Same type+normalized message+in-project frames  

Cases that must **not** share a group:

- Different exception types  
- Different in-project functions  
- Meaningfully different messages after normalization  

CI fails if group partition ≠ expected partition.

---

## 6. API surface (public)

```python
# Supported
from failtree import Tracker

t = Tracker("runs.db", label="nightly")
with t:
    with t.item("a.csv", stage="parse"):
        ...
    @t.track(stage="parse")
    def process(path: str): ...

# CLI
# failtree summary|view|export ...
```

**Not public (v1):** Storage, Fingerprinter, widgets — advanced users may import at own risk; semver only guarantees `Tracker` + CLI.

---

## 7. Error handling policy

| Situation | Behavior |
|-----------|----------|
| DB path not writable | Fail fast at Tracker init |
| Schema older | Migrate or clear error with message |
| Exception during persist | Log to stderr; do not mask original user exception (chain if needed) |
| TUI missing Textual | Exit 2 with install hint |
| Empty DB / no runs | CLI prints friendly empty state |

---

## 8. Testing strategy

| Layer | Tests |
|-------|-------|
| fingerprint | Parametrize over fixtures; normalization unit tests |
| chains | Synthetic `__cause__`, `__context__`, `ExceptionGroup`, cycles, depth cap |
| storage | Temp DB; concurrency smoke (threads); unique item upsert |
| tracker | Integration: fake pipeline writes expected counts |
| export/summary | Query correctness |
| viewer | Textual `pilot` for open/expand/quit (week 3+) |

Multiprocess stress: `examples/` or `tests/capture/test_multiprocess.py` with `multiprocessing.Pool` writing N items.

---

## 9. Configuration

v1: constructor args only.  

v1.x: optional `[tool.failtree]` in `pyproject.toml` or `failtree.toml`:

```toml
[tool.failtree]
project_roots = ["src"]
top_frames = 3
strip_quoted_strings = true
sample_cap = 5
busy_timeout_ms = 5000
```

---

## 10. Post-v1 LLD hooks (do not implement yet)

### 10.1 Gates

Add nullable `gate TEXT CHECK(gate IN ('OR','AND'))` on a future `nodes` view or on synthetic stage nodes. Default OR for batch aggregation. Viewer badge: `OR` / `AND`.

### 10.2 Observed impact

```sql
SELECT fingerprint, count,
       Round(100.0 * count / (SELECT COUNT(*) FROM items WHERE run_id=? AND status='failed'), 1)
         AS pct_of_failures
FROM groups ...
```

### 10.3 faultree JSON export

Map:

| failtree | faultree JSON |
|----------|---------------|
| Run | `event_type=top`, `gate=OR` |
| Stage aggregate | `intermediate`, `gate=OR` |
| Group | `basic`, `prob=observed_rate` |
| children | nested `children` arrays |

Adapter module: `failtree/core/faultree_export.py` (future).

---

## 11. Implementation checklist (LLD → code)

1. [ ] Schema + `Storage` migrations  
2. [ ] Fingerprint + fixtures  
3. [ ] Group upsert  
4. [ ] Chain walker  
5. [ ] Tracker `item()` + decorator  
6. [ ] Summary + export + CLI  
7. [ ] Thread retry + multiprocess stress  
8. [ ] Textual app lazy tree  
9. [ ] Example pipeline + README GIF  
10. [ ] CI matrix 3.9–3.13  

This order matches [ROADMAP.md](./ROADMAP.md).
