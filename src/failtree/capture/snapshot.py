"""Snapshot source files referenced by exception frames (P6)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from failtree.common.hashing import sha256_hex
from failtree.common.paths import is_external_frame, is_in_project
from failtree.core.models import StackFrame

# Keep DB small; skip huge generated files.
_MAX_BYTES = 256 * 1024


def collect_snapshot_paths(
    frames: Iterable[StackFrame],
    *,
    project_roots: Sequence[Path] = (),
) -> List[Path]:
    """Unique existing source paths from frames (in-project preferred)."""
    roots = tuple(Path(p) for p in project_roots)
    seen: Set[str] = set()
    out: List[Path] = []
    for frame in frames:
        raw = (frame.file or "").strip()
        if not raw or raw.startswith("<"):
            continue
        path = Path(raw)
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved)
        if key in seen:
            continue
        if roots:
            if not is_in_project(str(resolved), tuple(roots)):
                continue
        elif is_external_frame(str(resolved)):
            continue
        if not resolved.is_file():
            continue
        seen.add(key)
        out.append(resolved)
    return out


def read_source_file(path: Path, *, max_bytes: int = _MAX_BYTES) -> Optional[str]:
    """Read a text source file; return None if missing/binary/too large."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > max_bytes:
        return None
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return None


def hash_content(content: str) -> str:
    return sha256_hex(content)


def snapshot_frames(
    frames: Sequence[StackFrame],
    *,
    project_roots: Sequence[Path] = (),
) -> List[Tuple[str, str, str]]:
    """Return list of (path, content_hash, content) for snapshotable frames."""
    rows: List[Tuple[str, str, str]] = []
    for path in collect_snapshot_paths(frames, project_roots=project_roots):
        content = read_source_file(path)
        if content is None:
            continue
        rows.append((str(path), hash_content(content), content))
    return rows
