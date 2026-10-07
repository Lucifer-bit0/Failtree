# Announcement draft (v1.0)

Short posts you can paste after PyPI is live. Edit links as needed.

## r/Python / r/dataengineering

**Title:** failtree — local SQLite error triage for batch/ETL pipelines

I open-sourced **failtree**: a library you import into a pipeline to capture
per-item failures, group them by root-cause fingerprint, browse parent/child
exception trees in a Textual TUI (works over SSH), export retry lists, diff
runs, and correlate likely code changes — all on a local SQLite file. No server.

```bash
pip install failtree
python examples/fake_pipeline.py   # from the repo
failtree summary examples/fake_runs.db
```

Not a Sentry/Datadog replacement and not a log search tool. Aimed at data
engineers who already dig through stack traces after a nightly job.

Repo: https://github.com/Lucifer-bit0/Failtree  
PyPI: https://pypi.org/project/failtree/

## Textual community

failtree ships an optional Textual TUI (`pip install "failtree[tui]"`) for
browsing grouped pipeline errors over SSH / `docker exec -it`. Feedback on the
tree + detail layout welcome.
