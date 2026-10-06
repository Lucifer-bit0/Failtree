# failtree — High-Level Design (HLD)

## 1. Purpose

**failtree** is a local-first library and terminal viewer for data/ETL pipelines. It records per-item outcomes, captures exception chains, groups failures by root-cause fingerprint, and helps operators export retry lists.

It is **not** a hosted error tracker, log aggregator, or APM.

---

## 2. Goals and non-goals

### 2.1 Goals

1. **Zero-config capture** inside existing Python loops (`Tracker` + `item()`).
2. **Root-cause grouping** so operators triage a few groups, not thousands of rows.
3. **Exception causality trees** (`__cause__`, `__context__`, `ExceptionGroup`).
4. **Batch awareness**: item, stage, status, attempts, run summary.
5. **Actionable export**: failed keys for retry.
6. **Local-only**: single SQLite file; data never leaves the machine unless the user copies the file.
7. **Terminal-native**: Textual TUI + plain CLI for minimal environments.

### 2.2 Non-goals (v1)

- HTTP ingest server / multi-tenant SaaS  
- Web UI  
- Alerting integrations  
- LLM-based RCA  
- Full application logging / metrics  
- Classical fault-tree quantification engines (see post-v1)

---

## 3. Personas and use cases

| Persona | Need | Primary surface |
|---------|------|-----------------|
| Data engineer | “Which files failed parse, and why?” | Tracker API + CLI export |
| On-call / ops | “Is this run healthy? Top root causes?” | TUI + `summary` |
| Platform eng | “Safe to embed in workers?” | Thread/process-safe storage |
| Reliability eng (later) | “Export observed tree to FTA tools” | faultree JSON (post-v1) |

### Primary use cases

1. Wrap a file/batch loop; continue or fail-fast; inspect groups after the run.  
2. Live-watch a long job in the TUI (refreshing summary).  
3. Export `ValueError` failures to `retry.txt` and re-run.  
4. Drill into a group → item → chained exceptions.

---

## 4. System context

```
┌──────────────────────────────────────────────────────────────┐
│                     User environment                         │
│  ┌────────────┐   ┌─────────────┐   ┌─────────────────────┐  │
│  │ Pipeline / │   │  Workers    │   │  Human operator     │  │
│  │ ETL script │   │  (mp/threads│   │  terminal           │  │
│  └─────┬──────┘   └──────┬──────┘   └──────────┬──────────┘  │
│        │ Tracker.item()  │                      │ failtree   │
│        └────────┬────────┘                      │ cli / tui  │
│                 ▼                               ▼            │
│        ┌────────────────────────────────────────────┐        │
│        │              failtree library              │        │
│        │     capture  →  core  ←  viewer/cli        │        │
│        └────────────────────┬───────────────────────┘        │
│                             ▼                                │
│                      ┌────────────┐                          │
│                      │  runs.db   │  (SQLite, WAL)           │
│                      └────────────┘                          │
└──────────────────────────────────────────────────────────────┘

External systems (none required for v1).
Optional later: faultree CLI/API consumes exported JSON.
```

**Trust boundary:** the DB may contain paths, messages, and tracebacks. v1.x should add redaction; v1 documents “treat `runs.db` as sensitive.”

---

## 5. Logical architecture

### 5.1 Layers

```
┌─────────────────────────────────────────┐
│ viewer   Textual app · CLI entrypoints  │  presentation
├─────────────────────────────────────────┤
│ capture  Tracker · decorator · chains   │  instrumentation
├─────────────────────────────────────────┤
│ core     models · storage · fingerprint │  domain + persistence
└─────────────────────────────────────────┘
```

**Dependency rule:** `viewer` → `core`; `capture` → `core`; `core` has no dependency on viewer or capture. CLI may call core directly (summary/export) without loading Textual.

### 5.2 Components

| Component | Responsibility |
|-----------|----------------|
| **Tracker** | Opens/creates DB, starts/ends a run, exposes `item()` / decorator |
| **ItemContext** | Marks status, attempts, captures exceptions on exit |
| **ChainWalker** | Expands exception graphs into stored error nodes |
| **Fingerprinter** | Normalizes + hashes for grouping |
| **Storage** | SQLite schema, WAL pragmas, CRUD, batched writes |
| **GroupService** | Upserts groups, maintains counts / sample examples |
| **SummaryService** | Aggregates ok/failed/retried/skipped + rates |
| **ExportService** | Writes retry lists filtered by type/stage/status |
| **TuiApp** | Lazy tree, detail panel, live header, keybindings |
| **CLI** | `summary`, `view`, `export` commands |

### 5.3 Data stores

| Store | Form | Lifetime |
|-------|------|----------|
| `runs.db` | SQLite file path chosen by user | Durable artifact of one or many runs |
| In-memory Tracker state | Current `run_id`, optional write buffer | Process lifetime |

No network store in v1.

---

## 6. Key data concepts

| Concept | Meaning |
|---------|---------|
| **Run** | One pipeline execution (label, start/end) |
| **Item** | One unit of work (file, batch id, partition) |
| **Stage** | Logical step name (`parse`, `validate`, `load`) |
| **Error** | One exception node (may have parent) |
| **Group** | Cluster of errors sharing a fingerprint |
| **Fingerprint** | Stable hash of normalized root-cause identity |

Relationships:

```
Run 1──* Item 1──* Error
Error *──1 Group (via fingerprint)
Error parent_error_id → Error  (tree)
```

---

## 7. End-to-end flows

### 7.1 Capture (happy + failure)

```
User code enters with t.item(key, stage)
  → Storage.ensure_item(run_id, key, stage)
  → body runs
  → success: status=ok
  → exception:
       ChainWalker.walk(exc)
       for each node: Fingerprinter.fingerprint(node)
                      Storage.insert_error(...)
                      GroupService.upsert(...)
       status=failed (or retried semantics on re-entry)
       re-raise (default) OR suppress if continue_on_error
```

### 7.2 Triage (TUI)

```
Operator: failtree view runs.db
  → load run summary (header)
  → list groups ordered by count
  → expand group → items → errors (lazy)
  → select node → traceback + metadata (detail)
  → export retry list for selection / filter
```

### 7.3 Retry export (CLI)

```
failtree export runs.db --failed-type ValueError --stage parse -o retry.txt
  → query distinct item keys matching filters
  → write one key per line
```

---

## 8. Cross-cutting concerns

### 8.1 Concurrency

| Mode | Approach (v1) | Escalate (v1.x) |
|------|---------------|-----------------|
| Threads | Shared connection with lock **or** per-thread connections + `busy_timeout` | — |
| Processes | Each worker opens DB; WAL + `busy_timeout` + retry on `SQLITE_BUSY` | Single-writer process + queue |
| TUI + live run | Reader connections `read_uncommitted` / short queries; refresh every N seconds | — |

### 8.2 Performance

- Batch inserts when capturing many errors in one chain.  
- Indexes on `fingerprint`, `item_id`, `(run_id, status)`.  
- Cap stored example errors per group (e.g. 5).  
- Lazy TUI loading — never load all errors at once.

### 8.3 Security / privacy

- No telemetry.  
- Document that DB may contain PII/secrets in messages.  
- Future: redaction hooks before insert.

### 8.4 Extensibility (without scope creep)

- Pluggable normalizer list (config).  
- Stable export schemas (retry list, later faultree JSON).  
- Optional `meta` JSON on runs for git sha / env — opaque to core.

---

## 9. Packaging and distribution

```
failtree/                  # import name
  core/
  capture/
  viewer/
  cli.py

pyproject.toml
  [project.scripts] failtree = failtree.cli:main
  optional-dependencies: tui = ["textual>=0.60"]
```

Install modes:

- `pip install failtree` — capture + CLI summary/export  
- `pip install failtree[tui]` — adds Textual viewer  

Supported Python: 3.9–3.13 (CI matrix). Dependency: `exceptiongroup` on &lt;3.11.

---

## 10. Quality attributes

| Attribute | Target |
|-----------|--------|
| Setup cost | ≤ 2 lines in user code |
| Grouping quality | Golden fixtures; tunable normalizers |
| Capture overhead | Negligible vs I/O-bound ETL (measure in examples) |
| Multiprocess | Correct under N workers (stress test) |
| Offline | 100% functional without network |
| Testability | core 100% unit-tested without Textual |

---

## 11. Future architecture (post-v1)

Borrowed from classical FTA / `faultree` package — **observational**, not guessed:

1. **Gate vocabulary** — Mark intermediate nodes OR (any child fails) vs AND (all must fail). Default batch/stage = OR.  
2. **Observed probabilities** — `P(group) ≈ count(group) / failed_items` for impact ranking.  
3. **Export** — Emit `faultree` JSON (`id`, `name`, `event_type`, `gate`, `children`, `prob`) for reliability tooling.

These do not change the v1 layer split; they add fields/export adapters on top of existing trees and counts.

See [ROADMAP.md](./ROADMAP.md).

---

## 12. Risks (architectural)

| Risk | Mitigation |
|------|------------|
| Fingerprint over/under-grouping | Fixtures, raw retention, pluggable rules, later split/merge |
| SQLite writer contention | Early stress test; writer queue if needed |
| TUI schedule slip | CLI summary/export before TUI polish |
| Scope creep to mini-Sentry | Hard non-goals; no web/alerts in v1 |
| Name collision | Confirm PyPI/GitHub before publish |

---

## 13. HLD summary

failtree is a **three-layer, local SQLite system** that instruments pipeline items, persists exception trees, groups by fingerprint, and presents triage via CLI/TUI. The architectural center of gravity is **core** (schema + fingerprint). Capture and viewer are thin, replaceable shells around that core.
