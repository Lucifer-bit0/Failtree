# failtree

**Local-first error triage for batch / ETL pipelines.**

Capture per-item failures into SQLite, group them by root-cause fingerprint, browse parent/child exception trees in a terminal UI, export retry lists, diff runs, and correlate likely code changes — without a server.

[![CI](https://github.com/Lucifer-bit0/Failtree/actions/workflows/ci.yml/badge.svg)](https://github.com/Lucifer-bit0/Failtree/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/failtree.svg)](https://pypi.org/project/failtree/)
[![Python](https://img.shields.io/pypi/pyversions/failtree.svg)](https://pypi.org/project/failtree/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

![failtree demo](docs/demo.svg)

## Install (under 1 minute)

```bash
pip install failtree
# optional Textual TUI:
pip install "failtree[tui]"
```

From GitHub / a clone:

```bash
pip install "git+https://github.com/Lucifer-bit0/Failtree.git"
pip install -e ".[dev]"
```

## 5-minute quickstart

```bash
git clone https://github.com/Lucifer-bit0/Failtree.git
cd Failtree
pip install -e ".[dev]"
python examples/fake_pipeline.py
failtree summary examples/fake_runs.db
failtree export examples/fake_runs.db -o retry.txt --stage parse
failtree view examples/fake_runs.db          # needs failtree[tui]
```

Code-change correlation (offline):

```bash
python examples/correlate_demo.py
```

## Two lines in your pipeline

```python
import failtree

failtree.init("runs.db", label="nightly-etl")

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

Or wrap `main`:

```python
from failtree import run, get_tracker

def main() -> None:
    t = get_tracker()
    with t.item("file.csv", stage="parse"):
        process("file.csv")

if __name__ == "__main__":
    run(main, db_path="runs.db", label="nightly-etl")
```

### Catch import / startup crashes (Docker)

```bash
failtree run --db /data/runs.db --label my-service -- python -m my_service
```

```dockerfile
ENTRYPOINT ["failtree", "run", "--db", "/data/runs.db", "--label", "my-service", "--"]
CMD ["python", "-m", "my_service"]
```

## CLI

```bash
failtree summary runs.db
failtree export runs.db -o retry.txt --stage parse --failed-type ValueError
failtree diff runs.db 1 2                   # new / fixed / persisting / regressed
failtree correlate runs.db 1 2              # likely related code changes
failtree run --db runs.db -- python app.py
failtree view runs.db                       # Textual TUI
failtree view runs.db --diff 1 2
```

TUI keys: `/` search · `f` stage filter · `e` export · `c` run diff · `r` refresh · `d` switch DB · `q` quit

## What it is / isn't

| Is | Isn't |
|----|--------|
| Library + local SQLite | Hosted APM (Sentry / Datadog) |
| Root-cause grouping + trees | General log search (use lnav) |
| Batch item / retry export | AI-first debugging (optional later) |
| Run diff + code correlation | Proof that a commit caused a bug |

## Docs

| Doc | Topic |
|-----|--------|
| [docs/DATA_AND_REDACTION.md](docs/DATA_AND_REDACTION.md) | **What gets stored** and redaction |
| [docs/EVENT_SCHEMA.md](docs/EVENT_SCHEMA.md) | Persisted entities |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers and boundaries |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases through v1.0 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup and PR norms |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |
| [docs/ANNOUNCE.md](docs/ANNOUNCE.md) | Draft announcement text |

## Status

**v1.0.0** — P0–P7 complete. Python 3.9–3.13.

## Layout

```
src/failtree/
  common/    # shared helpers
  core/      # models, schema, storage, fingerprint, diff, correlate
  capture/   # Tracker, hooks, redaction, snapshots
  viewer/    # Textual TUI
  cli.py
examples/    # fake_pipeline, correlate_demo
```
