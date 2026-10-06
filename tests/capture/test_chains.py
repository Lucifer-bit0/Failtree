from __future__ import annotations

import sys

from failtree.capture.chains import leaf_indices, walk_exception


def test_cause_chain_order_and_leaves() -> None:
    try:
        try:
            raise ValueError("inner")
        except ValueError as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError as outer:
        nodes = walk_exception(outer)

    assert len(nodes) == 2
    assert nodes[0].relation == "root"
    assert type(nodes[0].exc).__name__ == "RuntimeError"
    assert nodes[1].relation == "cause"
    assert nodes[1].parent_index == 0
    assert leaf_indices(nodes) == [1]


def test_context_when_no_cause() -> None:
    try:
        try:
            raise ValueError("first")
        except ValueError:
            raise RuntimeError("second")  # noqa: B904
    except RuntimeError as outer:
        nodes = walk_exception(outer)

    assert any(n.relation == "context" for n in nodes)


def test_cycle_guard() -> None:
    a = ValueError("a")
    b = RuntimeError("b")
    a.__cause__ = b
    b.__cause__ = a
    nodes = walk_exception(a)
    assert len(nodes) == 2


def test_exception_group_children() -> None:
    if sys.version_info >= (3, 11):
        group_cls = BaseExceptionGroup  # type: ignore[name-defined]
    else:
        from exceptiongroup import BaseExceptionGroup as group_cls

    group = group_cls("many", [ValueError("one"), TypeError("two")])
    nodes = walk_exception(group)
    assert nodes[0].relation == "root"
    children = [n for n in nodes if n.relation == "group_child"]
    assert len(children) == 2
    assert set(leaf_indices(nodes)) == {1, 2}
