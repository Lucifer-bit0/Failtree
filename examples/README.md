# Examples

| Script | What it shows |
|--------|----------------|
| `fake_pipeline.py` | Tracker capture, fingerprint groups, summary/export |
| `correlate_demo.py` | Two runs + edited worker → `failtree correlate` |

```bash
# from repo root
pip install -e ".[dev]"
python examples/fake_pipeline.py
failtree summary examples/fake_runs.db

python examples/correlate_demo.py
```

Michigan well-log downloader (repo root, needs `requests` + network):

```bash
python michigan.py --inject-errors --limit 12 --workers 4 --fresh-db
python michigan.py --correlate-demo --limit 12 --workers 4
```
