"""Correlate source-file changes between runs with error frames (P6).

Honesty rule: this is **correlation**, not proof that a change caused the failure.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from failtree.core.models import (
    CorrelatedChange,
    CorrelateRank,
    CorrelationReport,
)
from failtree.core.storage import Storage


def correlate_runs(
    storage: Storage,
    before_run_id: int,
    after_run_id: int,
    *,
    fingerprint: Optional[str] = None,
    max_diff_lines: int = 80,
) -> CorrelationReport:
    """Rank file changes against frames from the after run's failures."""
    before = storage.get_run(before_run_id)
    after = storage.get_run(after_run_id)
    if before is None:
        raise ValueError(f"run not found: {before_run_id}")
    if after is None:
        raise ValueError(f"run not found: {after_run_id}")
    if before_run_id == after_run_id:
        raise ValueError("before and after run ids must differ")

    before_files = {r.path: r.content_hash for r in storage.list_run_files(before_run_id)}
    after_files = {r.path: r.content_hash for r in storage.list_run_files(after_run_id)}

    frame_hints = storage.list_frame_hints_for_run(
        after_run_id, fingerprint=fingerprint
    )
    # path -> set of function names (root-cause first already preferred by caller query)
    root_funcs: Dict[str, Set[str]] = {}
    parent_funcs: Dict[str, Set[str]] = {}
    for path, func, is_root in frame_hints:
        norm = _norm_path(path)
        bucket = root_funcs if is_root else parent_funcs
        bucket.setdefault(norm, set()).add(func)

    all_frame_paths = set(root_funcs) | set(parent_funcs)
    # Also match by basename when absolute paths differ across machines.
    basename_to_norms: Dict[str, Set[str]] = {}
    for p in set(before_files) | set(after_files) | all_frame_paths:
        basename_to_norms.setdefault(Path(p).name.lower(), set()).add(_norm_path(p))

    changed_paths = _changed_paths(before_files, after_files)
    changes: List[CorrelatedChange] = []

    for path in sorted(changed_paths):
        npath = _norm_path(path)
        matched_path, funcs, via_root = _match_frames(
            npath, root_funcs, parent_funcs, basename_to_norms
        )
        if matched_path is None and npath not in all_frame_paths:
            # Only report changes that touch files seen in after-run frames.
            if Path(path).name.lower() not in {
                Path(p).name.lower() for p in all_frame_paths
            }:
                continue

        before_hash = before_files.get(path)
        after_hash = after_files.get(path)
        before_text = storage.get_code_blob(before_hash) if before_hash else None
        after_text = storage.get_code_blob(after_hash) if after_hash else None
        diff = _unified_diff(
            before_text or "",
            after_text or "",
            path=path,
            max_lines=max_diff_lines,
        )

        func_hit = _function_hit(funcs, before_text or "", after_text or "")
        if func_hit and via_root:
            rank = CorrelateRank.SAME_FUNCTION
            confidence = "high"
            note = f"same function in root-cause frames: {func_hit}"
        elif func_hit:
            rank = CorrelateRank.SAME_FUNCTION
            confidence = "medium"
            note = f"same function in parent frames: {func_hit}"
        elif matched_path is not None or npath in all_frame_paths:
            rank = CorrelateRank.SAME_FILE
            confidence = "medium" if via_root else "low"
            note = "file appears in traceback frames"
        else:
            rank = CorrelateRank.RELATED_FILE
            confidence = "low"
            note = "changed alongside failing run (weak signal)"

        changes.append(
            CorrelatedChange(
                path=path,
                rank=rank,
                confidence=confidence,
                function=func_hit,
                before_hash=before_hash,
                after_hash=after_hash,
                unified_diff=diff,
                note=note,
            )
        )

    rank_order = {
        CorrelateRank.SAME_FUNCTION: 0,
        CorrelateRank.SAME_FILE: 1,
        CorrelateRank.RELATED_FILE: 2,
    }
    conf_order = {"high": 0, "medium": 1, "low": 2}
    changes.sort(key=lambda c: (rank_order[c.rank], conf_order.get(c.confidence, 9), c.path))

    if not changes:
        message = "no related code change found"
    else:
        message = (
            f"{len(changes)} likely related change(s) "
            "(correlation, not proof)"
        )

    return CorrelationReport(
        before_run_id=before_run_id,
        after_run_id=after_run_id,
        before_version=before.code_version,
        after_version=after.code_version,
        changes=tuple(changes),
        message=message,
    )


def format_correlation_report(report: CorrelationReport) -> str:
    lines = [
        f"correlate: run {report.before_run_id} -> run {report.after_run_id}",
        f"before_version: {report.before_version or '-'}",
        f"after_version:  {report.after_version or '-'}",
        f"result: {report.message}",
    ]
    if not report.changes:
        return "\n".join(lines)

    for i, change in enumerate(report.changes, 1):
        lines.append("")
        lines.append(
            f"{i}. [{change.confidence}] {change.rank.value}  {change.path}"
        )
        if change.function:
            lines.append(f"   function: {change.function}")
        lines.append(f"   note: {change.note}")
        if change.unified_diff:
            lines.append("   --- diff ---")
            for dline in change.unified_diff.splitlines():
                lines.append(f"   {dline}")
    return "\n".join(lines)


def _changed_paths(
    before_files: Dict[str, str], after_files: Dict[str, str]
) -> Set[str]:
    paths = set(before_files) | set(after_files)
    out: Set[str] = set()
    for path in paths:
        if before_files.get(path) != after_files.get(path):
            out.add(path)
    return out


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").lower()


def _match_frames(
    npath: str,
    root_funcs: Dict[str, Set[str]],
    parent_funcs: Dict[str, Set[str]],
    basename_to_norms: Dict[str, Set[str]],
) -> Tuple[Optional[str], Set[str], bool]:
    if npath in root_funcs:
        return npath, root_funcs[npath], True
    if npath in parent_funcs:
        return npath, parent_funcs[npath], False
    base = Path(npath).name.lower()
    for candidate in basename_to_norms.get(base, ()):
        if candidate in root_funcs:
            return candidate, root_funcs[candidate], True
        if candidate in parent_funcs:
            return candidate, parent_funcs[candidate], False
    return None, set(), False


def _function_hit(
    funcs: Set[str], before_text: str, after_text: str
) -> Optional[str]:
    if not funcs:
        return None
    # Prefer a function whose definition line appears in the unified sense
    # (name present in either version). Order deterministically.
    for name in sorted(funcs):
        if not name or name.startswith("<"):
            continue
        needle = f"def {name}"
        if needle in before_text or needle in after_text:
            return name
        # Still credit the frame function even without a def line match.
        return name
    return None


def _unified_diff(
    before: str,
    after: str,
    *,
    path: str,
    max_lines: int,
) -> str:
    if before == after:
        return ""
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{Path(path).name}",
        tofile=f"b/{Path(path).name}",
        lineterm="",
    )
    lines = list(diff)
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines truncated)"]
    return "\n".join(lines)
