"""Synthetic failure injectors for michigan.py / correlate demos.

This file is intentionally mutated by ``--correlate-demo`` between runs so
failtree can snapshot a real source change and show it in ``correlate``.
"""

from __future__ import annotations

import uuid

# Demo marker - correlate-demo flips this comment/version between runs.
FAULT_VERSION = "v1"


def inject_test_error(well_id: str, index: int) -> None:
    """Raise synthetic errors so failtree grouping/chains can be verified.

    Pattern by index % 5:
      0,1 -> ValueError with different UUIDs/paths (should share one group)
      2   -> RuntimeError HTTP-style failure
      3   -> chained KeyError -> RuntimeError (parent/child tree)
      4   -> no inject (real download path)
    """
    bucket = index % 5
    if bucket in (0, 1):
        raise ValueError(
            f"simulated corrupt PDF stream id={uuid.uuid4()} "
            f"path=/data/wells/{well_id}.pdf"
        )
    if bucket == 2:
        raise RuntimeError(f"HTTP 503 for wellLogID={well_id}")
    if bucket == 3:
        try:
            raise KeyError(well_id)
        except KeyError as exc:
            raise RuntimeError(f"metadata missing for wellLogID={well_id}") from exc
    # bucket == 4: fall through to real download
