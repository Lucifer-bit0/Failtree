"""Hash helpers shared by fingerprinting and any future identity keys."""

from __future__ import annotations

import hashlib


def short_sha256(text: str, *, length: int = 16) -> str:
    """Return the first ``length`` hex chars of SHA-256 over UTF-8 ``text``."""
    if length < 1:
        raise ValueError("length must be >= 1")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest[:length]
