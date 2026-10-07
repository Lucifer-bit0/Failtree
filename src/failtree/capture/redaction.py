"""Offline redaction of secrets before persistence."""

from __future__ import annotations

import re
from typing import Iterable, Pattern, Sequence, Tuple

# Atomic default patterns — reusable and extendable via init/Tracker.
_DEFAULT_PATTERNS: Tuple[Tuple[Pattern[str], str], ...] = (
    (re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"]+"), r"\1=<REDACTED>"),
    (re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"), "Bearer <REDACTED>"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
     "<REDACTED_PRIVATE_KEY>"),
)


def compile_extra_patterns(
    pairs: Sequence[Tuple[str, str]],
) -> Tuple[Tuple[Pattern[str], str], ...]:
    return tuple((re.compile(pat), repl) for pat, repl in pairs)


def redact_text(
    text: str,
    *,
    extra_patterns: Iterable[Tuple[Pattern[str], str]] = (),
) -> str:
    """Return ``text`` with known secret shapes replaced."""
    if not text:
        return text
    out = text
    for pattern, repl in _DEFAULT_PATTERNS:
        out = pattern.sub(repl, out)
    for pattern, repl in extra_patterns:
        out = pattern.sub(repl, out)
    return out
