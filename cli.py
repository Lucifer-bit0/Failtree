"""CLI entrypoint — summary/view/export grow in Phases 2–4."""

from __future__ import annotations

import argparse
import sys

from failtree._version import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="failtree", description="Pipeline error triage")
    parser.add_argument("--version", action="version", version=f"failtree {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("summary", help="Print a run summary (Phase 2)")
    sub.add_parser("view", help="Open the Textual TUI (Phase 3)")
    sub.add_parser("export", help="Export failed item keys (Phase 2)")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    print(
        f"Command '{args.command}' is not implemented yet "
        f"(core Phase 1 is available as a library).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
