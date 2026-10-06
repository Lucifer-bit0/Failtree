"""Run summary helpers (thin wrappers over Storage for future CLI use)."""

from __future__ import annotations

from failtree.core.models import RunSummary
from failtree.core.storage import Storage


def summarize_run(storage: Storage, run_id: int) -> RunSummary:
    """Return aggregate counts for a run."""
    return storage.get_summary(run_id)
