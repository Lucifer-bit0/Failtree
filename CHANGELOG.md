# Changelog

All notable changes to this project are documented in this file.

## [1.0.0] - 2026-10-07

First stable release (roadmap P0–P7).

### Added

- Local SQLite capture via `Tracker`, `failtree.init` / `run`, and `failtree run --`
- Root-cause fingerprinting, exception chains, OR/AND gates
- CLI: `summary`, `export`, `diff`, `correlate`, `view`, `run`
- Textual TUI: group → item → error tree, search, stage filter, multi-DB, run diff
- Batch ranking (% of failures), retry export
- Run diff: new / fixed / persisting / regressed
- Code-change correlation: version detect, traceback snapshots, ranked diffs
- Docs: architecture, event schema, data/redaction, contributing

### Security / privacy

- Default offline redaction of common secret patterns before persistence
- Source snapshots limited to traceback files (size-capped, project-root aware)

## [0.1.0] - 2026-10

Alpha through batch features (P0–P4) while the library was in active development.
