"""Group upsert logic.

``append_example_id`` is atomic and reusable.
``GroupService`` orchestrates a single store bump (DIP via Protocol).
"""

from __future__ import annotations

from typing import List, Optional, Protocol, Sequence


def append_example_id(
    example_ids: Sequence[int],
    error_id: int,
    *,
    sample_cap: int,
) -> List[int]:
    """Return a new capped example-id list including ``error_id`` when room."""
    if sample_cap < 1:
        return []
    updated = [int(x) for x in example_ids]
    if error_id in updated:
        return updated
    if len(updated) < sample_cap:
        updated.append(error_id)
    return updated


class GroupStore(Protocol):
    """Persistence port for group bumps — implemented by :class:`Storage`."""

    def bump_group(
        self,
        *,
        fingerprint: str,
        title: str,
        error_id: int,
        ts: Optional[str] = None,
        sample_cap: int = 5,
    ) -> None: ...


class GroupService:
    """Application service around group counting (thin, testable)."""

    def __init__(self, store: GroupStore, *, sample_cap: int = 5) -> None:
        self._store = store
        self._sample_cap = sample_cap

    def bump(
        self,
        *,
        fingerprint: str,
        title: str,
        error_id: int,
        ts: Optional[str] = None,
    ) -> None:
        self._store.bump_group(
            fingerprint=fingerprint,
            title=title,
            error_id=error_id,
            ts=ts,
            sample_cap=self._sample_cap,
        )
