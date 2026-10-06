"""SQLite busy/locked write retries (reusable across capture writes)."""

from __future__ import annotations

import random
import sqlite3
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def is_busy_error(exc: BaseException) -> bool:
    """Return True if ``exc`` looks like a SQLite busy/locked error."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


def write_with_retry(
    fn: Callable[[], T],
    *,
    retries: int = 10,
    base_delay: float = 0.01,
) -> T:
    """Call ``fn`` retrying on SQLite busy/locked with exponential backoff."""
    last: BaseException | None = None
    for attempt in range(retries):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            last = exc
            if not is_busy_error(exc) or attempt == retries - 1:
                raise
            delay = base_delay * (2**attempt) * (0.5 + random.random())
            time.sleep(delay)
    assert last is not None
    raise last
