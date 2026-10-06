"""failtree — local pipeline error capture and root-cause grouping."""

from failtree._version import __version__
from failtree.capture import Tracker

__all__ = ["Tracker", "__version__"]
