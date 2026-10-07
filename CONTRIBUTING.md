# Contributing to failtree

Thanks for helping. failtree stays a **library-first, local SQLite** tool for
batch/ETL error triage — not a hosted APM or log search platform.

## Setup

```bash
git clone https://github.com/Lucifer-bit0/Failtree.git
cd Failtree
python -m pip install -e ".[dev]"
python -m pytest -q
```

Optional TUI-only install: `pip install -e ".[tui]"`.

## Development norms

- **Python 3.9+** (CI runs 3.9–3.13).
- Prefer small, focused PRs that match an existing phase/roadmap item.
- Fail-open: capture code must never crash the host pipeline.
- Keep layers clear: `capture` → `ErrorSink` → `core` storage; viewer/CLI read-only.
- Do not add network calls, cloud backends, or LLM uploads without an explicit
  opt-in design discussion.

## Checks before you push

```bash
python -m ruff check src tests
python -m pytest -q
```

## Docs worth reading

- [docs/ROADMAP.md](docs/ROADMAP.md) — phases and non-goals
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layout and boundaries
- [docs/DATA_AND_REDACTION.md](docs/DATA_AND_REDACTION.md) — what gets stored
- [docs/EVENT_SCHEMA.md](docs/EVENT_SCHEMA.md) — persisted entities

## Release (maintainers)

1. Bump version in `pyproject.toml` and `src/failtree/_version.py`.
2. Update [CHANGELOG.md](CHANGELOG.md).
3. Tag `vX.Y.Z` and push; the Publish workflow builds and uploads to PyPI when
   trusted publishing is configured on the GitHub repo.
