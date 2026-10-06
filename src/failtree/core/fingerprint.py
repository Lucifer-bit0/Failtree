"""Root-cause fingerprinting.

Classes follow SRP:
- MessageNormalizer  — strip volatile tokens from messages
- FrameSelector      — pick in-project frames for the fingerprint
- Fingerprinter      — orchestrate normalize + frames + hash
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

from failtree.common.hashing import short_sha256
from failtree.common.paths import frame_file_basename, is_external_frame, is_in_project
from failtree.core.models import StackFrame

# Atomic compiled patterns — reused everywhere normalization runs.
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_ISO_TS_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
)
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{7,}\b")
_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\|/)[^\s:'\"]+"
)
_QUOTED_RE = re.compile(r"(['\"])(?:\\.|(?!\1).)*\1")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class FingerprintConfig:
    """Open for extension: add patterns without changing Fingerprinter code."""

    project_roots: Tuple[Path, ...] = ()
    top_frames: int = 3
    strip_quoted_strings: bool = True
    hash_length: int = 16
    extra_patterns: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FingerprintResult:
    fingerprint: str
    normalized_message: str
    title: str
    identity: str  # pre-hash material (useful in tests/debug)


class MessageNormalizer:
    """Normalize exception messages by replacing volatile tokens."""

    def __init__(self, config: FingerprintConfig) -> None:
        self._strip_quoted = config.strip_quoted_strings
        self._extra = tuple(
            (re.compile(pattern), repl) for pattern, repl in config.extra_patterns
        )

    def normalize(self, message: str) -> str:
        text = message or ""
        text = _UUID_RE.sub("<UUID>", text)
        text = _ISO_TS_RE.sub("<TS>", text)
        text = _PATH_RE.sub("<PATH>", text)
        if self._strip_quoted:
            text = _QUOTED_RE.sub("<STR>", text)
        text = _HEX_RE.sub("<HEX>", text)
        text = _NUM_RE.sub("<NUM>", text)
        for pattern, repl in self._extra:
            text = pattern.sub(repl, text)
        return _WS_RE.sub(" ", text).strip()


class FrameSelector:
    """Select the most relevant in-project stack frames for grouping."""

    def __init__(self, config: FingerprintConfig) -> None:
        self._roots = config.project_roots
        self._top_n = config.top_frames

    def select(self, frames: Sequence[StackFrame]) -> Tuple[StackFrame, ...]:
        if not frames:
            return ()

        if self._roots:
            chosen = [f for f in frames if is_in_project(f.file, self._roots)]
        else:
            chosen = [f for f in frames if not is_external_frame(f.file)]

        if not chosen:
            # Fall back to last N frames (closest to raise site in usual order).
            chosen = list(frames)

        # Prefer frames nearest the throw site (end of list).
        return tuple(chosen[-self._top_n :])


class Fingerprinter:
    """Compose message normalization + frame selection into a stable hash."""

    def __init__(self, config: Optional[FingerprintConfig] = None) -> None:
        self.config = config or FingerprintConfig()
        self._normalizer = MessageNormalizer(self.config)
        self._frames = FrameSelector(self.config)

    def fingerprint(
        self,
        exc_type: str,
        message: str,
        frames: Sequence[StackFrame] | Iterable[StackFrame] = (),
    ) -> FingerprintResult:
        frame_list = tuple(frames)
        normalized = self._normalizer.normalize(message)
        selected = self._frames.select(frame_list)
        frame_part = ">".join(
            f"{frame_file_basename(f.file)}:{f.func}" for f in selected
        )
        identity = f"{exc_type}|{normalized}|{frame_part}"
        digest = short_sha256(identity, length=self.config.hash_length)
        title = f"{exc_type}: {normalized[:120]}" if normalized else exc_type
        return FingerprintResult(
            fingerprint=digest,
            normalized_message=normalized,
            title=title,
            identity=identity,
        )
