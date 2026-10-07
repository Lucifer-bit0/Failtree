"""Retry-list export helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from failtree.core.storage import Storage


def export_failed_keys(
    storage: Storage,
    run_id: int,
    dest: str | Path,
    *,
    exc_type: Optional[str] = None,
    stage: Optional[str] = None,
    fingerprint: Optional[str] = None,
) -> int:
    """Write failed item keys (one per line). Returns number of keys written."""
    keys: Sequence[str] = storage.iter_failed_keys(
        run_id, exc_type=exc_type, stage=stage, fingerprint=fingerprint
    )
    path = Path(dest)
    path.write_text("\n".join(keys) + ("\n" if keys else ""), encoding="utf-8")
    return len(keys)
