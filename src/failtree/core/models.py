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


@dataclass(frozen=True)
class Run:
    id: int
    label: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]
    status: RunStatus
    meta: dict[str, Any] = field(default_factory=dict)


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


@dataclass(frozen=True)
class Group:
    fingerprint: str
    title: str
    count: int
    first_seen: datetime
    last_seen: datetime
    example_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    total: int
    ok: int
    failed: int
    skipped: int
    recovered: int
    groups: int
    progress_per_sec: Optional[float] = None


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


@dataclass(frozen=True)
class StackFrame:
    file: str
    func: str
    line: int
