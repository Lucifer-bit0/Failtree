# failtree — Architecture Overview

Working name: **failtree** (rename before PyPI publish if needed: `pipefault`, `batcherr`).

This pack is the source of truth for what we build, what we defer, and the order of work.

| Document | Purpose |
|----------|---------|
| [HLD.md](./HLD.md) | High-level design: goals, context, components, flows, roadmap |
| [LLD.md](./LLD.md) | Low-level design: schema, APIs, algorithms, modules, tests |
| [ROADMAP.md](./ROADMAP.md) | Phased path: v1 → v1.x → post-v1 (faultree crossover) |

Companion exploration notes live in the Cursor canvas review (product positioning, competitors, naming).

---

## One-sentence product

Wrap a service’s `main` (and each unit of work) so failures — including boot/import issues via an outer launcher — land in local SQLite, grouped by root cause, with CLI/TUI/API triage.

---

## Integration model (how other services plug in)

```
Docker / server ENTRYPOINT
        │
        │  failtree run --db /data/runs.db -- python -m my_service
        │  (catches import/syntax/exit of the child process)
        ▼
┌─────────────────── my_service ───────────────────┐
│  from failtree import run, get_tracker           │
│  def main():                                     │
│      t = get_tracker()                           │
│      with t.item(...): ...                       │
│  run(main, db_path=...)   # Tracker before main  │
└──────────────────────────────────────────────────┘
        │
        ▼
   runs.db  ◄──── future: HTTP API / UI (list runs, groups, errors)
```

| Layer | Catches |
|-------|---------|
| `failtree.run(main)` | Failures inside `main` + imports triggered from `main` |
| `failtree run -- cmd` | Child process import/syntax/crash before app code runs |
| Future HTTP API | Read same DB from other services / dashboards |

---

## System at a glance

```
  Your pipeline code
        │
        │  from failtree import run, get_tracker
        │  run(main)  /  with t.item(key, stage="parse"): ...
        ▼
  ┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
  │   capture   │────▶│      core        │◀────│     viewer      │
  │ Tracker API │     │ models · storage │     │ Textual TUI     │
  │ bootstrap   │     │ fingerprint      │     │ + CLI summary   │
  └─────────────┘     └────────┬─────────┘     └─────────────────┘
                               │
                               ▼
                        runs.db (SQLite WAL)
                        runs · items · errors · groups
```

Three layers stay separate so each can be tested alone:

| Layer | Responsibility | Depends on |
|-------|----------------|------------|
| **core** | Data model, SQLite, fingerprinting, queries | stdlib + `exceptiongroup` (backport) |
| **capture** | User-facing Tracker / decorator / chains / bootstrap | core (via **sink** interface) |
| **viewer** | Textual TUI + plain CLI | core (never capture) |

### Sink interface (future-proofing)

Capture must not talk to SQLite types directly forever. Introduce an `ErrorSink` protocol:

```
capture (Tracker / hooks)
        │  emit(run/item/error events)
        ▼
   ErrorSink  ──► SqliteSink (v1)
              └──► HttpSink  (later server)
```

Refactor target: `Storage` implements `ErrorSink`; Tracker depends on the protocol only. See [ROADMAP.md](./ROADMAP.md).

---

## What we can do (capability map)

### Must ship (v1)

| Capability | User value |
|------------|------------|
| Zero-config `Tracker` + `item()` context manager | One-line setup inside ETL loops |
| Decorator form `@t.track(stage=...)` | Function-shaped jobs |
| Exception capture with traceback | Failures never silently disappear |
| Parent/child trees (`__cause__`, `__context__`, `ExceptionGroup`) | See what actually caused what |
| Root-cause fingerprint grouping | 10k errors → handful of distinct bugs |
| Item → stage → status + attempts | Batch awareness (ok/failed/retried/skipped) |
| Run summary (totals, rates) | Know if the job is healthy |
| Export failed keys (`--failed-type`) | Feed a retry list |
| Textual TUI (group → item → error) | Interactive triage |
| CLI `summary` / `view` / `export` | Works on minimal terminals |
| Thread-safe writes; multiprocess-safe enough | Real pipelines use workers |
| Python 3.9+, MIT (or Apache-2.0), single `runs.db` | Easy adoption |

### Should ship soon after v1 (v1.x)

| Capability | Why |
|------------|-----|
| Impact ranking (“group X = 71% of failures”) | Observed probabilities; almost free from counts |
| Pluggable normalization rules | Fix over/under-grouping without code changes |
| Split / merge groups (manual) | Escape hatch when fingerprinting is wrong |
| `continue_on_error` batch mode | Process all files; collect failures |
| Single-writer queue for heavy multiprocess | Scale writes when busy-timeout is not enough |
| Optional sample of successful items | Progress without huge DBs |
| Secrets redaction in messages/tracebacks | Safer sharing of `runs.db` |

### Can do later (post-v1 / faultree crossover)

| Capability | Why later |
|------------|-----------|
| OR/AND gate labels on tree nodes | FTA vocabulary; needs stable tree UX first |
| Export to `faultree` JSON | Reliability tooling interop; niche ask |
| Web dashboard | Scope creep toward Beacon; resist unless demanded |
| Slack / email alerts | Ops product; not the wedge |
| LLM RCA / embeddings | Optional; stay deterministic first |
| OpenTelemetry export | Enterprise integration later |
| Cross-run regression (“quiet 7d, spiked today”) | Needs multi-run analytics |

### Explicit non-goals

- Replacing Sentry / Datadog APM  
- Full log aggregation (use `lnav`, etc.)  
- Remote ingest HTTP server in v1  
- Guessed reliability probabilities (we use **observed** rates only)

---

## Path we should follow

```
Week 1  core          schema · storage · fingerprint + golden fixtures
Week 2  capture       Tracker · chains · thread/process safety
        ↳ early CLI   summary + export (pull forward from week 4)
Week 3  viewer        Textual tree · detail · lazy load · live refresh
Week 4  batch polish  retry filters · progress · docs examples
Week 5  release       GIF · CI matrix · PyPI · community posts
────────────────────────────────────────────────────────────────
v1.x    impact rank · normalizer config · split/merge · writer queue
post    gates (OR/AND) · faultree JSON export · (maybe) alerts
```

**Critical rule:** do not start the Textual app until fingerprint fixtures pass and a fake pipeline can write through `core.storage`.

**Schedule tweak vs original plan:** ship CLI `summary` + `export` as soon as capture works (end of week 2), so the product is useful before the TUI is polished.

---

## Decision log (locked for v1)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.9+ | Skills match; Textual; data-eng users |
| Storage | One SQLite file, WAL | Zero ops; portable artifact |
| License | MIT (default) | Fast adoption; Apache-2.0 OK if patent grant wanted |
| Layers | core / capture / viewer | Independent testability |
| Fingerprint | type + normalized msg + top N in-project frames | Proven pattern; tunable |
| Capture default | Record then **re-raise** | Safe; opt-in `continue_on_error` |
| TUI dependency | Extra: `failtree[tui]` | Headless CI stays light |
| Name | `failtree` (working) | Free on PyPI probe; tree metaphor |

---

## Document ownership

Update HLD when product scope changes. Update LLD when schema/API/algorithms change. Update ROADMAP when milestones slip or v1.x priorities reorder.
