# failtree

Local-first error capture for data/ETL pipelines: record per-item outcomes, group root causes, inspect exception trees, export retry lists.

## Install

```bash
pip install "git+https://github.com/Lucifer-bit0/Failtree.git"
# or from a clone:
pip install -e ".[dev]"
```

## Quick start — wrap your service `main`

**Option A — `init()` then use the tracker anywhere:**

```python
import failtree

failtree.init("runs.db", label="my-service")  # hooks + heartbeat on

def main() -> None:
    t = failtree.get_tracker()
    for path in files:
        with t.item(path, stage="parse"):
            process(path)

if __name__ == "__main__":
    try:
        main()
    finally:
        failtree.shutdown()
```

**Option B — pass `main` into `run()` (Tracker starts first):**

```python
from failtree import run, get_tracker

def main() -> None:
    t = get_tracker()
    for path in files:
        with t.item(path, stage="parse"):
            process(path)

if __name__ == "__main__":
    run(main, db_path="runs.db", label="my-service")
```

That catches failures inside `main` and imports that happen *from* `main`.

### Catch import/syntax failures of the whole script (Docker / server)

Start failtree **outside** the app process:

```bash
failtree run --db /data/runs.db --label my-service -- python -m my_service
```

Dockerfile sketch:

```dockerfile
ENTRYPOINT ["failtree", "run", "--db", "/data/runs.db", "--label", "my-service", "--"]
CMD ["python", "-m", "my_service"]
```

### Lower-level Tracker API

```python
from failtree import Tracker

with Tracker("runs.db", label="nightly", continue_on_error=True) as t:
    with t.item("file.csv", stage="parse"):
        process("file.csv")
```

## CLI

```bash
failtree summary runs.db
failtree export runs.db -o retry.txt --stage parse --failed-type ValueError
failtree run --db runs.db -- python broken_app.py
failtree view michigan_runs.db              # Textual TUI (needs failtree[tui])
failtree view runs.db other.db              # multi-DB switcher
```

TUI keys: `/` search · `f` stage filter · `e` export retry.txt · `r` refresh · `d` switch DB · `q` quit

## Demo

```bash
python examples/fake_pipeline.py
failtree summary examples/fake_runs.db
```

## Status

- **Phase 1:** core storage + fingerprinting  
- **Phase 2:** Tracker capture, exception chains, CLI summary/export  
- **Phase 3:** Textual TUI (next)

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Layout

```
src/failtree/
  common/    # shared atomic helpers
  core/      # models, schema, storage, fingerprint, grouping
  capture/   # Tracker, chains, concurrency
  viewer/    # Textual TUI (Phase 3)
  cli.py
```
