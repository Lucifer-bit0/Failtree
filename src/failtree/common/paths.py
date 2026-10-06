"""Path / stack-frame classification helpers."""

from __future__ import annotations

import sys
from pathlib import Path


def frame_file_basename(file_path: str) -> str:
    """Return the basename of a traceback file path (stable across machines)."""
    if not file_path:
        return "<unknown>"
    return Path(file_path).name


def _norm(path: str) -> str:
    return path.replace("\\", "/").lower()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_external_frame(file_path: str) -> bool:
    """Return True if the frame is likely stdlib, venv, or non-file.

    Used so fingerprinting can prefer in-project frames.
    """
    if not file_path or file_path.startswith("<"):
        return True

    norm = _norm(file_path)
    if any(
        marker in norm
        for marker in (
            "/site-packages/",
            "/dist-packages/",
            "/lib/python",
            "/lib64/python",
        )
    ):
        return True

    try:
        resolved = Path(file_path).resolve()
    except OSError:
        return True

    for prefix in (sys.prefix, sys.base_prefix):
        try:
            root = Path(prefix).resolve()
        except OSError:
            continue
        if _is_relative_to(resolved, root):
            parts = {_norm(p) for p in resolved.parts}
            if "site-packages" in parts or "dist-packages" in parts:
                return True
            if "lib" in parts or "lib64" in parts or "libs" in parts:
                return True
    return False


def is_in_project(file_path: str, project_roots: tuple[Path, ...]) -> bool:
    """Return True if ``file_path`` sits under any of ``project_roots``."""
    if not file_path or not project_roots:
        return False
    try:
        resolved = Path(file_path).resolve()
    except OSError:
        return False
    for root in project_roots:
        try:
            if _is_relative_to(resolved, root.resolve()):
                return True
        except OSError:
            continue
    return False
