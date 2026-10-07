"""Compare two runs by root-cause fingerprint (P5)."""

from __future__ import annotations

from typing import Dict, List, Tuple

from failtree.core.models import DiffKind, FingerprintDelta, RunDiff
from failtree.core.storage import Storage


def compare_runs(storage: Storage, before_run_id: int, after_run_id: int) -> RunDiff:
    """Classify fingerprints as new / fixed / persisting / regressed.

    Counts are distinct failed items per fingerprint in each run.
    Persisting includes equal counts and improvements (e.g. 32 → 5).
    Regressed means the same fingerprint hit more items (e.g. 5 → 32).
    """
    if before_run_id == after_run_id:
        raise ValueError("before and after run ids must differ")
    if storage.get_run(before_run_id) is None:
        raise ValueError(f"run not found: {before_run_id}")
    if storage.get_run(after_run_id) is None:
        raise ValueError(f"run not found: {after_run_id}")

    before = storage.fingerprint_counts_for_run(before_run_id)
    after = storage.fingerprint_counts_for_run(after_run_id)

    new: List[FingerprintDelta] = []
    fixed: List[FingerprintDelta] = []
    persisting: List[FingerprintDelta] = []
    regressed: List[FingerprintDelta] = []

    all_fps = set(before) | set(after)
    for fp in sorted(all_fps):
        b = int(before.get(fp, {}).get("count", 0))
        a = int(after.get(fp, {}).get("count", 0))
        title = _title_for(fp, before, after)
        if b == 0 and a > 0:
            new.append(
                FingerprintDelta(
                    fingerprint=fp,
                    title=title,
                    kind=DiffKind.NEW,
                    before_count=0,
                    after_count=a,
                )
            )
        elif b > 0 and a == 0:
            fixed.append(
                FingerprintDelta(
                    fingerprint=fp,
                    title=title,
                    kind=DiffKind.FIXED,
                    before_count=b,
                    after_count=0,
                )
            )
        elif a > b:
            regressed.append(
                FingerprintDelta(
                    fingerprint=fp,
                    title=title,
                    kind=DiffKind.REGRESSED,
                    before_count=b,
                    after_count=a,
                )
            )
        else:
            # a > 0 and b > 0 and a <= b
            persisting.append(
                FingerprintDelta(
                    fingerprint=fp,
                    title=title,
                    kind=DiffKind.PERSISTING,
                    before_count=b,
                    after_count=a,
                )
            )

    new.sort(key=lambda d: (-d.after_count, d.fingerprint))
    fixed.sort(key=lambda d: (-d.before_count, d.fingerprint))
    persisting.sort(key=lambda d: (-d.before_count, d.fingerprint))
    regressed.sort(key=lambda d: (-(d.after_count - d.before_count), d.fingerprint))

    return RunDiff(
        before_run_id=before_run_id,
        after_run_id=after_run_id,
        new=tuple(new),
        fixed=tuple(fixed),
        persisting=tuple(persisting),
        regressed=tuple(regressed),
    )


def format_diff_report(diff: RunDiff) -> str:
    """Plain-text report for CLI / minimal terminals."""
    lines = [
        f"diff: run {diff.before_run_id} -> run {diff.after_run_id}",
        f"new:        {len(diff.new)}",
        f"fixed:      {len(diff.fixed)}",
        f"persisting: {len(diff.persisting)}",
        f"regressed:  {len(diff.regressed)}",
    ]
    sections: List[Tuple[str, Tuple[FingerprintDelta, ...]]] = [
        ("NEW", diff.new),
        ("FIXED", diff.fixed),
        ("PERSISTING", diff.persisting),
        ("REGRESSED", diff.regressed),
    ]
    for label, rows in sections:
        if not rows:
            continue
        lines.append("")
        lines.append(f"{label}:")
        for row in rows:
            lines.append(
                f"  {row.before_count} -> {row.after_count}  {row.title}  "
                f"({row.fingerprint})"
            )
    return "\n".join(lines)


def _title_for(
    fingerprint: str,
    before: Dict[str, Dict[str, object]],
    after: Dict[str, Dict[str, object]],
) -> str:
    for src in (after, before):
        if fingerprint in src:
            title = src[fingerprint].get("title")
            if title:
                return str(title)
    return fingerprint
