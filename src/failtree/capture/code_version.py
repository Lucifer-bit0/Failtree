"""Detect a code version string for a run (P6).

Order:
1. ``FAILTREE_GIT_SHA`` or ``GIT_SHA`` environment variable (Docker bake-in)
2. ``git rev-parse HEAD`` when a ``.git`` directory is reachable
3. Otherwise unknown (caller may fall back to content hashes only)
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


@dataclass(frozen=True)
class CodeVersion:
    version: str
    source: str  # env | git | unknown


def detect_code_version(
    *,
    cwd: str | Path | None = None,
    project_roots: Sequence[str | Path] = (),
) -> CodeVersion:
    """Best-effort code version; never raises."""
    for key in ("FAILTREE_GIT_SHA", "GIT_SHA"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return CodeVersion(version=value[:64], source="env")

    search_roots: list[Path] = []
    if cwd is not None:
        search_roots.append(Path(cwd))
    search_roots.extend(Path(p) for p in project_roots)
    if not search_roots:
        search_roots.append(Path.cwd())

    seen: set[Path] = set()
    for root in search_roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in seen:
            continue
        seen.add(resolved)
        sha = _git_rev_parse(resolved)
        if sha:
            return CodeVersion(version=sha, source="git")

    return CodeVersion(version="unknown", source="unknown")


def _git_rev_parse(start: Path) -> Optional[str]:
    git_dir = _find_git_dir(start)
    if git_dir is None:
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(git_dir.parent if git_dir.name == ".git" else git_dir),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    sha = (proc.stdout or "").strip()
    return sha[:64] if sha else None


def _find_git_dir(start: Path) -> Optional[Path]:
    current = start if start.is_dir() else start.parent
    for _ in range(12):
        candidate = current / ".git"
        if candidate.exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None
