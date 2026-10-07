"""Textual TUI viewer."""

from __future__ import annotations

__all__ = ["run_viewer"]


def run_viewer(*args, **kwargs):
    from failtree.viewer.app import run_viewer as _run

    return _run(*args, **kwargs)
