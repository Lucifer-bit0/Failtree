"""Immutable domain models (dataclasses). No I/O here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"


class ItemStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    RETRIED = "retried"
    SKIPPED = "skipped"


class Gate(str, Enum):
    """Fault-tree style marker on parent error nodes (P4)."""

    OR = "OR"  # fails if any child fails (default for batches / ExceptionGroup)
    AND = "AND"  # fails only if all children fail


@dataclass(frozen=True)
class Run:
    id: int
    label: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]
    status: RunStatus
    meta: dict[str, Any] = field(default_factory=dict)
    code_version: Optional[str] = None
    code_version_source: Optional[str] = None


@dataclass(frozen=True)
class RunFile:
    """Source file snapshot linked to a run (content keyed by hash)."""

    run_id: int
    path: str
    content_hash: str


class CorrelateRank(str, Enum):
    """How closely a file change matches error frames (P6)."""

    SAME_FUNCTION = "same_function"
    SAME_FILE = "same_file"
    RELATED_FILE = "related_file"


@dataclass(frozen=True)
class CorrelatedChange:
    """One likely-related source change between two runs (correlation, not proof)."""

    path: str
    rank: CorrelateRank
    confidence: str  # high | medium | low
    function: Optional[str]
    before_hash: Optional[str]
    after_hash: Optional[str]
    unified_diff: str
    note: str = ""


@dataclass(frozen=True)
class CorrelationReport:
    """Code-change correlation between before_run and after_run."""

    before_run_id: int
    after_run_id: int
    before_version: Optional[str]
    after_version: Optional[str]
    changes: tuple[CorrelatedChange, ...] = ()
    message: str = ""  # e.g. no related code change found


@dataclass(frozen=True)
class Item:
    id: int
    run_id: int
    key: str
    stage: str
    status: ItemStatus
    attempts: int


@dataclass(frozen=True)
class ErrorRecord:
    id: int
    item_id: int
    parent_error_id: Optional[int]
    depth: int
    exc_type: str
    message: str
    normalized_message: str
    traceback: str
    fingerprint: str
    ts: datetime
    is_group_root: bool
    gate: Optional[Gate] = None


@dataclass(frozen=True)
class Group:
    fingerprint: str
    title: str
    count: int
    first_seen: datetime
    last_seen: datetime
    example_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class GroupImpact:
    """Failure-rate ranking row for a root-cause group within a run."""

    fingerprint: str
    title: str
    count: int
    failed_items: int
    pct_of_failures: float


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    total: int
    ok: int
    failed: int
    skipped: int
    retried: int
    recovered: int
    groups: int
    progress_per_sec: Optional[float] = None


class DiffKind(str, Enum):
    """Classification of a fingerprint across two runs (P5)."""

    NEW = "new"  # present only in the after run
    FIXED = "fixed"  # present only in the before run
    PERSISTING = "persisting"  # in both; count same or down
    REGRESSED = "regressed"  # in both; count went up


@dataclass(frozen=True)
class FingerprintDelta:
    """One fingerprint's change between two runs."""

    fingerprint: str
    title: str
    kind: DiffKind
    before_count: int
    after_count: int


@dataclass(frozen=True)
class RunDiff:
    """Full fingerprint comparison of before_run → after_run."""

    before_run_id: int
    after_run_id: int
    new: tuple[FingerprintDelta, ...] = ()
    fixed: tuple[FingerprintDelta, ...] = ()
    persisting: tuple[FingerprintDelta, ...] = ()
    regressed: tuple[FingerprintDelta, ...] = ()

    @property
    def all_deltas(self) -> tuple[FingerprintDelta, ...]:
        return self.new + self.fixed + self.persisting + self.regressed


@dataclass(frozen=True)
class NewError:
    """Payload for inserting one error node (no DB id yet)."""

    item_id: int
    parent_error_id: Optional[int]
    depth: int
    exc_type: str
    message: str
    normalized_message: str
    traceback: str
    fingerprint: str
    ts: str
    is_group_root: bool = False
    gate: Optional[str] = None  # "OR" | "AND" | None


@dataclass(frozen=True)
class StackFrame:
    file: str
    func: str
    line: int
