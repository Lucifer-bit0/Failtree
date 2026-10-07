"""Run summary + failure-rate ranking helpers."""

from __future__ import annotations

from typing import List

from failtree.core.models import GroupImpact, RunSummary
from failtree.core.storage import Storage


def summarize_run(storage: Storage, run_id: int) -> RunSummary:
    """Return aggregate counts for a run."""
    return storage.get_summary(run_id)


def rank_groups(storage: Storage, run_id: int, *, limit: int = 20) -> List[GroupImpact]:
    """Return groups ranked by % of failed items in the run."""
    return storage.rank_groups(run_id, limit=limit)


def format_summary_report(
    summary: RunSummary,
    impacts: List[GroupImpact] | None = None,
) -> str:
    """Plain-text report for CLI / minimal terminals."""
    lines = [
        f"run_id:    {summary.run_id}",
        f"total:     {summary.total}",
        f"ok:        {summary.ok}",
        f"failed:    {summary.failed}",
        f"retried:   {summary.retried}",
        f"skipped:   {summary.skipped}",
        f"recovered: {summary.recovered}",
        f"groups:    {summary.groups}",
    ]
    if impacts:
        lines.append("")
        lines.append("failure-rate ranking (% of failed items):")
        for impact in impacts:
            lines.append(
                f"  {impact.pct_of_failures:5.1f}%  "
                f"({impact.failed_items} items)  {impact.title}  "
                f"({impact.fingerprint})"
            )
    return "\n".join(lines)
