"""failtree — local pipeline error capture and root-cause grouping."""

from failtree._version import __version__
from failtree.capture import Tracker, get_tracker, init, run, run_command, shutdown

__all__ = [
    "Tracker",
    "get_tracker",
    "init",
    "run",
    "run_command",
    "shutdown",
    "__version__",
]
