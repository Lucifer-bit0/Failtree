"""Walk exception causality graphs into a flat parent-linked node list."""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from typing import List, Optional, Sequence

from failtree.core.models import StackFrame

if sys.version_info >= (3, 11):
    _BaseExceptionGroup = BaseExceptionGroup  # noqa: F821
else:  # pragma: no cover - exercised on 3.9/3.10 CI
    from exceptiongroup import BaseExceptionGroup as _BaseExceptionGroup


@dataclass(frozen=True)
class ChainNode:
    """One exception in a walked tree (parent referenced by list index)."""

    exc: BaseException
    parent_index: Optional[int]
    depth: int
    relation: str  # root | cause | context | group_child


def extract_frames(exc: BaseException) -> tuple[StackFrame, ...]:
    """Atomic helper: pull stack frames from an exception traceback."""
    frames: List[StackFrame] = []
    tb = exc.__traceback__
    if tb is None:
        return ()
    try:
        for entry in traceback.extract_tb(tb):
            frames.append(
                StackFrame(
                    file=entry.filename or "",
                    func=entry.name or "<unknown>",
                    line=int(entry.lineno or 0),
                )
            )
    except Exception:  # pragma: no cover - defensive
        return ()
    return tuple(frames)


def format_exception_text(exc: BaseException) -> str:
    """Atomic helper: render a traceback string; never raises."""
    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:  # pragma: no cover - defensive
        return "<unavailable>"


def walk_exception(
    exc: BaseException,
    *,
    max_depth: int = 16,
) -> List[ChainNode]:
    """Walk ``__cause__`` / ``__context__`` / ExceptionGroup into ordered nodes.

    Parents always appear before children so storage can resolve negative
    parent index refs: ``parent_error_id = -(parent_index + 1)``.
    """
    nodes: List[ChainNode] = []
    seen: set[int] = set()

    def visit(
        current: BaseException,
        parent_index: Optional[int],
        depth: int,
        relation: str,
    ) -> None:
        if depth > max_depth:
            return
        cid = id(current)
        if cid in seen:
            return
        seen.add(cid)
        index = len(nodes)
        nodes.append(
            ChainNode(
                exc=current,
                parent_index=parent_index,
                depth=depth,
                relation=relation,
            )
        )

        if isinstance(current, _BaseExceptionGroup):
            for child in current.exceptions:
                visit(child, index, depth + 1, "group_child")

        cause = current.__cause__
        if cause is not None:
            visit(cause, index, depth + 1, "cause")
            return

        if getattr(current, "__suppress_context__", False):
            return
        context = current.__context__
        if context is not None:
            visit(context, index, depth + 1, "context")

    visit(exc, None, 0, "root")
    return nodes


def leaf_indices(nodes: Sequence[ChainNode]) -> List[int]:
    """Return indices of nodes that have no children in ``nodes``."""
    parents = {
        n.parent_index for n in nodes if n.parent_index is not None
    }
    return [i for i in range(len(nodes)) if i not in parents]
