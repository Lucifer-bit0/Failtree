"""Small JSON helpers so call sites do not re-implement dumps/loads defaults."""

from __future__ import annotations

import json
from typing import Any

_MISSING = object()


def dumps_json(value: Any) -> str:
    """Serialize ``value`` to a compact JSON string."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def loads_json(text: str | None, *, default: Any = _MISSING) -> Any:
    """Deserialize JSON.

    If ``text`` is empty/None or invalid and ``default`` was provided, return it.
    Otherwise re-raise :class:`json.JSONDecodeError`.
    """
    if text is None or text == "":
        if default is not _MISSING:
            return default
        raise json.JSONDecodeError("Expecting value", "", 0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if default is not _MISSING:
            return default
        raise
