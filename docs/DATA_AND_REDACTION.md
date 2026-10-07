# What failtree stores (secrets & redaction)

failtree is **local-first**: everything is written to a SQLite file you choose
(e.g. `runs.db`). Nothing is sent to a remote service unless you add a custom
sink later.

## Stored by default

| Data | Where | Notes |
|------|--------|--------|
| Run label, timestamps, status, heartbeat | `runs` | Optional `meta` JSON |
| Code version string | `runs.code_version` | From `FAILTREE_GIT_SHA` / `GIT_SHA` / `git rev-parse` |
| Item keys, stage, status, attempts | `items` | Keys are whatever you pass to `tracker.item(...)` |
| Exception type, message, traceback | `errors` | After optional redaction |
| Normalized message + fingerprint | `errors` / `groups` | For grouping only |
| Source file snapshots | `code_blobs` / `run_files` | Only files seen in tracebacks; ≤256 KiB; text only |

## Redaction (on by default)

When `redact=True` (default on `Tracker` / `init`):

- Patterns like `api_key=…`, `token=…`, `password=…` → `<REDACTED>`
- `Bearer …` tokens → `Bearer <REDACTED>`
- PEM private key blocks → `<REDACTED_PRIVATE_KEY>`

Add project-specific patterns:

```python
import failtree

failtree.init(
    "runs.db",
    extra_redact_patterns=[
        (r"(?i)account[_-]?id\s*[:=]\s*\S+", "account_id=<REDACTED>"),
    ],
)
```

```python
from failtree import Tracker

with Tracker(
    "runs.db",
    extra_redact_patterns=[
        (r"(?i)account[_-]?id\s*[:=]\s*\S+", "account_id=<REDACTED>"),
    ],
) as t:
    ...
```

Disable only if you accept raw secrets in the DB:

```python
Tracker("runs.db", redact=False)
```

## What redaction does *not* cover

- Item **keys** you choose (filenames, well IDs, emails) are stored as-is.
- Source **snapshots** are file contents on disk; redact messages/tracebacks, not
  necessarily every secret that appears only inside a `.py` file.
- Fingerprint normalization strips UUIDs/paths/numbers for grouping, but the
  raw (redacted) message is still stored for triage.

## Operational tips

1. Keep `runs.db` on a private volume; treat it like application logs.
2. Prefer opaque item keys when possible (`job-042` vs PII).
3. Set `project_roots=` so snapshots stay inside your repo, not site-packages.
4. For Docker, bake `GIT_SHA` and mount the DB path explicitly.

See also [EVENT_SCHEMA.md](EVENT_SCHEMA.md).
