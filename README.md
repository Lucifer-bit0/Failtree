# failtree

Local-first error capture for data/ETL pipelines: record per-item outcomes, group root causes, inspect exception trees, export retry lists.

## Install

```bash
pip install "git+https://github.com/Lucifer-bit0/Failtree.git"
# or from a clone:
pip install -e ".[dev]"
```

## Quick start

```python
from failtree import Tracker

t = Tracker("runs.db", label="nightly", continue_on_error=True)
with t:
    for path in files:
        with t.item(path, stage="parse"):
            process(path)

print(t.summary())
```

Decorator form:

```python
@t.track(stage="parse")
def process(path: str) -> None:
    ...
```

## CLI

```bash
failtree summary runs.db
failtree export runs.db -o retry.txt --stage parse --failed-type ValueError
```

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
