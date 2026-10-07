# Failtree Roadmap

## The idea in one line

**A terminal-first, library-first error tracker for batch pipelines**: capture failures, group them by root cause, explore them as a parent/child tree, and see what changed between runs and in the code.

## Major decisions (locked in)

| Decision | Choice |
|---|---|
| **Form** | Python library you import per project. No server needed for v1 |
| **Storage** | Local SQLite (WAL), one file per project |
| **UI** | Textual TUI. Works over SSH and `docker exec -it` |
| **Future-proofing** | A **sink interface** between capture and storage, so an HTTP server can be added later without a rewrite |
| **Suggestions** | Rule-based and offline. Always shows the raw evidence |
| **Differentiators** | Root-cause grouping, parent/child trees, per-item batch tracking, run diff, code-change correlation |
| **Non-goals** | General log search (lnav does it), hosted APM (Sentry/Datadog), AI-first debugging |

## Roadmap at a glance

```
P0 Foundations ─ P1 Core ─ P2 Capture ─ P3 Viewer ─ P4 Batch ──► v0.1 ALPHA
                                                                      │
                               P5 Run diff ─ P6 Code correlation ─ P7 Release ──► v1.0
```

Estimates assume part-time work and are rough: about **9 weeks to v1.0**, with an alpha around **week 5**.

## Current status (repo snapshot)

| Phase | Status | Notes |
|---|---|---|
| P0 Foundations | Done | Name, MIT, `pyproject`, CI, `docs/EVENT_SCHEMA.md`, `ErrorSink` / `SqliteSink` |
| P1 Core | Done | Schema v2 (+ heartbeat), fingerprint, storage, fixtures |
| P2 Capture | Done (for test gate) | `init()`, `run(main)`, hooks, redaction, heartbeat, fail-open, `failtree run --` |
| P3 Viewer | Done | Textual tree (group→item→error), detail, search, stage filter, multi-DB, live header |
| P4 Batch | Done | ranking % of failures, OR/AND gates, richer summary/export, schema v3 |
| P5 Run diff | Done | `failtree diff`, new/fixed/persisting/regressed, TUI `c` / `--diff` |
| P6 Code correlation | Done | code version, traceback snapshots, `failtree correlate`, TUI panel |
| P7 Release | Done | v1.0.0 docs, CI matrix+ruff, PyPI publish workflow, CONTRIBUTING |

> Note: `failtree run -- <cmd>` was built early (startup/import crashes). The roadmap below still lists it under “After v1.0” as an optional emphasis area; treat the CLI as already available.

## Phases

### P0: Foundations (week 0)
- **Check the name** on PyPI and GitHub. Avoid `faultree` and `rootcause`, which already exist
- Pick the license (**MIT or Apache-2.0**), create the repo, set up CI and `pyproject.toml`
- Write the **event schema** and the **sink interface**
- Collect a **test corpus of real, messy errors** from your own pipelines

**Exit:** the repo builds, tests run in CI, and the schema is written down.

### P1: Core (weeks 1-2)
- SQLite schema: `runs`, `items`, `errors` (with `parent_error_id`), `groups`
- **Fingerprinting:** normalize messages (strip IDs, numbers, paths, timestamps) and hash with the exception type and top in-project frames
- Storage layer with batched inserts and indexes

**Exit:** 10,000 synthetic errors collapse into the expected handful of groups, with tests proving it.

> **Make-or-break:** fingerprint quality. Over-grouping hides problems, under-grouping gives no value. Keep raw errors and make the rules adjustable.

### P2: Capture library (weeks 2-3)
- `failtree.init()` and `failtree.run(main)`
- `with tracker.item(file, stage=...)` context manager and a decorator form
- Global hooks: `sys.excepthook`, `threading.excepthook`, `sys.unraisablehook`, a `logging` handler, asyncio handler
- Walk `__cause__`, `__context__` and `ExceptionGroup` into parent/child records
- Heartbeat row, thread safety, multiprocessing guidance, redaction hook

**Exit:** a demo pipeline with threads and workers produces correct, complete records, and the library never crashes or blocks the host app.

> **Rule:** the tool must never be the reason your service fails. Fail open.

### P3: Viewer TUI (weeks 3-4)
- Tree: **group → item → error (with children)**, lazy-loaded on expand
- Detail panel with traceback, live refresh, search and filters
- **Multi-database switcher** (view several projects at once)
- Plain-text `failtree summary` for minimal terminals

**Exit:** open a DB with 100k+ errors and navigate it without lag.

### P4: Batch features (week 5) → **v0.1 alpha release**
- Item/stage/status tracking (ok, failed, retried, skipped)
- Run summary ("1,150 ok, 50 failed, 12 retried")
- **Export failed items as a retry list**
- Failure-rate ranking and optional OR/AND gate marker on parent errors

**Exit:** release the alpha, share it with a few data engineers, and collect feedback before building the harder features.

### P5: Run diff (week 6)
- Compare runs by fingerprint: **new / fixed / persisting / regressed**
- `failtree diff 11 12` and a diff view in the TUI

**Exit:** correct classification on test runs, including count changes (32 → 5).

### P6: Code-change correlation (weeks 7-8)
- Record the code version per run (`GIT_SHA` baked into the Docker image, or `git rev-parse`, or content hashes as a fallback)
- Snapshot only the files that appear in tracebacks (deduplicated by hash)
- Rank changes: same function > same file > imported file, starting with the **root-cause frames**, then the parents
- UI panel: "Likely related change," with confidence and the raw diff

**Exit:** on a test repo with an injected bug, the tool points at the right commit and function.

> **Honesty rule:** label it correlation, not proof. Show "no related code change found" when that's the truth.

### P7: Hardening and v1.0 release (week 9)
- README with a demo GIF, quickstart, and docs, plus `CONTRIBUTING.md`
- Example pipeline, CI across several Python versions
- Document exactly what gets stored (secrets and redaction)
- Publish to **PyPI** and announce (r/Python, r/dataengineering, Textual community)

**Exit:** a stranger can install it and see value in under 5 minutes.

## After v1.0 (only if there's demand)

1. `failtree run -- python main.py` wrapper for import and startup crashes *(CLI already exists in this repo — harden/document for production)*
2. HTTP sink plus a small server for multi-service setups
3. Log tailing and Docker event watching
4. Parsers or SDKs for other languages, OpenTelemetry input
5. Optional plugins: export to faultree JSON, RootCause or LLM-written explanations (opt-in, since they send data out)

## Top risks

| Risk | Plan |
|---|---|
| Fingerprinting quality | Test corpus from real pipelines, tunable rules, keep raw data |
| Hard crashes the library can't see (OOM, `kill -9`) | Heartbeat rows so the viewer shows "last seen X ago"; wrapper mode later |
| SQLite write contention | WAL, batched writes, single writer thread or queue |
| Secrets in tracebacks or snapshots | Redaction hook, store minimal data, clear docs |
| Scope creep into a log platform | Check every feature against the differentiators list |
| Misleading suggestions | Confidence labels, raw evidence always visible |

## How to know it's working

- You use it on your own pipelines and it replaces digging through log files
- A 100k-error run is understandable in **under a minute**
- Setup takes **two lines of code**
- A few outside users try the alpha and give feedback
- Early GitHub issues come from real use cases, not feature requests for log search

## Your next three actions

1. **Push v1.0.0** to GitHub and create a GitHub Release tag `v1.0.0`.
2. **Configure PyPI Trusted Publishing** for `.github/workflows/publish.yml`, then publish.
3. **Announce** using the draft in [docs/ANNOUNCE.md](ANNOUNCE.md).
