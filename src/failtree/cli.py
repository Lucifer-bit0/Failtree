"""CLI entrypoint: summary, export, run, view."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from failtree._version import __version__
from failtree.capture.bootstrap import run_command
from failtree.core.export import export_failed_keys
from failtree.core.storage import Storage
from failtree.core.summary import summarize_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="failtree", description="Pipeline error triage")
    parser.add_argument("--version", action="version", version=f"failtree {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_summary = sub.add_parser("summary", help="Print a run summary")
    p_summary.add_argument("db", type=Path, help="Path to runs.db")
    p_summary.add_argument("--run", type=int, default=None, help="Run id (default: latest)")

    p_export = sub.add_parser("export", help="Export failed item keys")
    p_export.add_argument("db", type=Path, help="Path to runs.db")
    p_export.add_argument("-o", "--output", type=Path, required=True, help="Output file")
    p_export.add_argument("--run", type=int, default=None, help="Run id (default: latest)")
    p_export.add_argument("--failed-type", dest="failed_type", default=None)
    p_export.add_argument("--stage", default=None)

    p_run = sub.add_parser(
        "run",
        help="Run a command and record startup/process failures into a DB",
    )
    p_run.add_argument(
        "--db",
        type=Path,
        default=Path("runs.db"),
        help="SQLite DB path (default: runs.db)",
    )
    p_run.add_argument("--label", default=None, help="Run label")
    p_run.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command after -- , e.g. failtree run --db x.db -- python app.py",
    )

    p_view = sub.add_parser("view", help="Open the Textual TUI")
    p_view.add_argument(
        "db",
        type=Path,
        nargs="*",
        help="One or more runs.db paths (multi-DB switcher)",
    )
    p_view.add_argument("--run", type=int, default=None, help="Focus a run id")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    if args.command == "view":
        return _cmd_view(args.db, args.run)
    if args.command == "summary":
        return _cmd_summary(args.db, args.run)
    if args.command == "export":
        return _cmd_export(
            args.db,
            args.output,
            run_id=args.run,
            exc_type=args.failed_type,
            stage=args.stage,
        )
    if args.command == "run":
        return _cmd_run(args.db, args.label, args.cmd)
    return 2


def _cmd_view(dbs: list[Path], run_id: int | None) -> int:
    paths = list(dbs) if dbs else [Path("runs.db")]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"Database not found: {missing[0]}", file=sys.stderr)
        return 2
    try:
        from failtree.viewer.app import run_viewer
    except ImportError:
        print(
            "Textual is required for the TUI. Install with:\n"
            '  pip install "failtree[tui]"\n'
            "Or use: failtree summary <db>",
            file=sys.stderr,
        )
        return 2
    run_viewer(paths, run_id=run_id)
    return 0


def _cmd_run(db: Path, label: str | None, cmd: list[str]) -> int:
    command = list(cmd)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print(
            "Usage: failtree run [--db runs.db] [--label name] -- <command> [args...]",
            file=sys.stderr,
        )
        return 2
    try:
        return run_command(command, db_path=db, label=label)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _resolve_run_id(storage: Storage, run_id: int | None) -> int:
    if run_id is not None:
        return run_id
    latest = storage.latest_run_id()
    if latest is None:
        raise SystemExit("No runs found in database")
    return latest


def _cmd_summary(db: Path, run_id: int | None) -> int:
    with Storage(db) as storage:
        rid = _resolve_run_id(storage, run_id)
        summary = summarize_run(storage, rid)
        groups = storage.list_groups(limit=10)
        print(f"run_id:   {summary.run_id}")
        print(f"total:    {summary.total}")
        print(f"ok:       {summary.ok}")
        print(f"failed:   {summary.failed}")
        print(f"skipped:  {summary.skipped}")
        print(f"recovered:{summary.recovered}")
        print(f"groups:   {summary.groups}")
        if groups:
            print()
            print("top groups:")
            for g in groups:
                print(f"  {g.count:5d}  {g.title}  ({g.fingerprint})")
    return 0


def _cmd_export(
    db: Path,
    output: Path,
    *,
    run_id: int | None,
    exc_type: str | None,
    stage: str | None,
) -> int:
    with Storage(db) as storage:
        rid = _resolve_run_id(storage, run_id)
        n = export_failed_keys(
            storage,
            rid,
            output,
            exc_type=exc_type,
            stage=stage,
        )
    print(f"Wrote {n} keys to {output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
