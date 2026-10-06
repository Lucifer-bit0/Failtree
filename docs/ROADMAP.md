# failtree — Roadmap & recommended path

This is the execution path. Prefer shipping vertical slices that a data engineer can use, over polishing UI early.

---

## Guiding principles

1. **Core first** — without schema + fingerprint, nothing else matters.  
2. **CLI before TUI** — summary/export unblock value if Textual slips.  
3. **Fixtures over opinions** — grouping quality is proven by golden tests.  
4. **Resist mini-Sentry** — no web, alerts, or ingest server until users demand them.  
5. **Park FTA ideas** — gates / faultree export after observational rankings exist.

---

## Phase 0 — Decisions (½ day)

| Action | Outcome |
|--------|---------|
| Confirm name (`failtree` / `pipefault`) | PyPI + GitHub reserved |
| License MIT or Apache-2.0 | `LICENSE` filed |
| Python 3.9+ | `requires-python` set |
| Read HLD/LLD | Team aligned |

**Exit:** empty repo with `pyproject.toml`, docs already in `docs/`.

---

## Phase 1 — Core (Week 1)

**Goal:** durable storage + trustworthy fingerprints.

| Deliverable | Done when |
|-------------|-----------|
| SQLite schema + WAL pragmas | Migrations apply on fresh DB |
| `Storage` CRUD | Unit tests on temp DB |
| Fingerprint normalizer | Golden fixture partition passes |
| Group upsert + example cap | Counts correct under duplicate inserts |
| Indexes | Explained queries for summary path |

**Do not build:** Tracker, TUI, CLI (except maybe a tiny debug script).

**Exit criteria:**  
`pytest tests/core` green on 3.9 and 3.12+.

---

## Phase 2 — Capture + early CLI (Week 2)

**Goal:** real pipelines can write failures; operators get text reports.

| Deliverable | Done when |
|-------------|-----------|
| `walk_exception` | cause/context/ExceptionGroup/cycle tests |
| `Tracker.item()` | Fake pipeline integration test |
| Decorator `@track` | Key extraction works |
| Re-raise vs `continue_on_error` | Both tested |
| Thread-safe writes | Concurrent test |
| Multiprocess smoke | N workers no corruption |
| `failtree summary` | Prints ok/failed/groups |
| `failtree export` | Retry file matches filters |

**Exit criteria:**  
`examples/fake_pipeline.py` produces a DB; `summary` + `export` work without Textual.

---

## Phase 3 — Viewer (Week 3)

**Goal:** interactive triage.

| Deliverable | Done when |
|-------------|-----------|
| Textual app shell | Opens DB, shows header |
| Lazy tree group→item→error | Expand loads children only |
| Detail panel | Traceback + metadata |
| Live refresh | Header updates while run grows |
| Keys `/` `f` `e` `q` | Documented in help |
| Optional extra | `pip install failtree[tui]` |

**Exit criteria:**  
Pilot test: open → expand → quit; manual demo on example DB.

---

## Phase 4 — Batch polish (Week 4)

| Deliverable | Done when |
|-------------|-----------|
| Stage/status filters in TUI + CLI | Documented |
| Progress rate in summary | Stable definition |
| Recovered-attempts reporting | Clear in UX |
| Richer export filters | `--stage`, `--failed-type`, `--run` |
| Docs polish | README quickstart accurate |

---

## Phase 5 — Release (Week 5)

| Deliverable | Done when |
|-------------|-----------|
| Demo GIF | Shows capture → TUI → export |
| CI (GitHub Actions) | 3.9–3.13 pytest |
| PyPI publish | `pip install failtree` works |
| Community posts | r/Python, r/dataengineering, Textual Discord |
| Feedback loop | Issue templates for grouping misses |

---

## Phase 6 — v1.x (after first users)

Priority order:

1. **Impact ranking** — `% of failures` per group (observed probabilities).  
2. **Pluggable normalizers** — config file / CLI flags.  
3. **Split / merge groups** — manual override when fingerprinting fails.  
4. **Secrets redaction** — before persist.  
5. **Single-writer queue** — if multiprocess stress demands it.  
6. **Success sampling** — optional, to shrink DB.

---

## Phase 7 — Post-v1 faultree crossover

Only when triage UX is solid:

1. OR/AND **gate labels** on aggregate nodes (batch = OR by default).  
2. Deeper impact analytics (per-stage contribution).  
3. **Export to faultree JSON** for reliability engineers.  
4. Revisit web/alerts only with clear demand.

---

## Path diagram

```
                 Phase 0  Name / license
                     │
                     ▼
                 Phase 1  core  ◄── fingerprint fixtures must pass
                     │
                     ▼
                 Phase 2  capture + CLI ──► useful without TUI (early adopters)
                     │
                     ▼
                 Phase 3  Textual TUI
                     │
                     ▼
                 Phase 4–5  polish + PyPI
                     │
                     ▼
                 v1.x  impact · normalizers · redaction
                     │
                     ▼
                 Post-v1  gates · faultree export

If TUI is delayed, stay on the CLI path — do not block release.
```

---

## What to do **next** (immediate)

1. Reserve **failtree** (or chosen name) on GitHub + PyPI.  
2. Scaffold `src/failtree/core/{models,storage,fingerprint}.py` per LLD.  
3. Add `tests/fixtures/messy_errors.json` from real pipeline errors if available.  
4. Implement Phase 1 only — resist Tracker/TUI until fixtures pass.

---

## Success metrics (v1)

| Metric | Target |
|--------|--------|
| Time to first capture | &lt; 5 minutes from README |
| Grouping demo | Example pipeline → ≤ 10 groups from ≥ 200 noisy errors |
| Export usefulness | Retry file re-runs only failed keys |
| Star/feedback | Qualitative: “I used this on a real job” |
