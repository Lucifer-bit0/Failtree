# failtree

Local-first error capture for data/ETL pipelines: record per-item outcomes, group root causes, inspect exception trees, export retry lists.

```python
from failtree import Tracker

t = Tracker("runs.db", label="nightly")
with t:
    with t.item("file.csv", stage="parse"):
        process("file.csv")
```

> **Status:** Phase 1 in progress — `core` (storage + fingerprinting). `Tracker` lands in Phase 2.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for HLD/LLD/roadmap.

## Install (dev)

```bash
pip install -e ".[dev]"
pytest
```

## Layout

```
src/failtree/
  common/    # shared atomic helpers (time, hash, json, paths)
  core/      # models, schema, storage, fingerprint, grouping
  capture/   # Tracker API (Phase 2)
  viewer/    # Textual TUI (Phase 3)
  cli.py
```
