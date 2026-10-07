"""Textual widgets for header + detail panel."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from failtree.core.models import (
    CorrelationReport,
    ErrorRecord,
    Group,
    Item,
    RunDiff,
    RunSummary,
)
from failtree.viewer.loading import BrowserSession, NodeRef


class SummaryHeader(Static):
    """Top bar: DB path + run counts."""

    DEFAULT_CSS = """
    SummaryHeader {
        height: 3;
        padding: 0 1;
        background: $boost;
        color: $text;
    }
    """

    def show(
        self,
        *,
        db_label: str,
        summary: Optional[RunSummary],
        filter_text: str = "",
        stage: str = "",
        diff: Optional[RunDiff] = None,
    ) -> None:
        if diff is not None:
            self.update(
                f"failtree  |  {db_label}  |  DIFF run {diff.before_run_id} -> "
                f"{diff.after_run_id}  new={len(diff.new)}  fixed={len(diff.fixed)}  "
                f"persist={len(diff.persisting)}  regressed={len(diff.regressed)}"
            )
            return
        if summary is None:
            self.update(f"failtree  |  {db_label}  |  (empty database)")
            return
        filt = ""
        if filter_text:
            filt += f"  search={filter_text!r}"
        if stage:
            filt += f"  stage={stage}"
        self.update(
            f"failtree  |  {db_label}  |  run={summary.run_id}  "
            f"ok={summary.ok}  failed={summary.failed}  "
            f"retried={summary.retried}  groups={summary.groups}{filt}"
        )


class DetailPanel(VerticalScroll):
    """Right-hand metadata + traceback for the selected node."""

    DEFAULT_CSS = """
    DetailPanel {
        width: 1fr;
        border-left: solid $primary;
        padding: 0 1;
    }
    DetailPanel > Label {
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Select a node", id="detail-title")
        yield Static("", id="detail-body")

    def show_placeholder(self, text: str = "Select a node") -> None:
        self.query_one("#detail-title", Label).update(text)
        self.query_one("#detail-body", Static).update("")

    def show_node(
        self,
        session: BrowserSession,
        ref: NodeRef,
        *,
        correlation: Optional[CorrelationReport] = None,
    ) -> None:
        title = self.query_one("#detail-title", Label)
        body = self.query_one("#detail-body", Static)
        corr_block = format_correlation_panel(correlation)

        if ref.kind == "diff_section" and ref.diff_kind:
            title.update(f"Diff section: {ref.diff_kind.upper()}")
            body.update(
                "new: only in after run\n"
                "fixed: only in before run\n"
                "persisting: in both, same or fewer items\n"
                "regressed: in both, more items than before"
            )
            return

        if ref.kind == "diff_row" and ref.fingerprint:
            title.update(f"{(ref.diff_kind or 'diff').upper()}  "
                         f"{ref.before_count} -> {ref.after_count}")
            group = session.get_group(ref.fingerprint)
            body.update(
                f"title: {ref.title or (group.title if group else ref.fingerprint)}\n"
                f"fingerprint: {ref.fingerprint}\n"
                f"kind: {ref.diff_kind}\n"
                f"before_count: {ref.before_count}\n"
                f"after_count: {ref.after_count}\n"
                + (
                    f"first_seen: {group.first_seen.isoformat()}\n"
                    f"last_seen: {group.last_seen.isoformat()}\n"
                    if group
                    else ""
                )
                + corr_block
            )
            return

        if ref.kind == "group" and ref.fingerprint:
            group = session.get_group(ref.fingerprint)
            if group is None:
                self.show_placeholder("Group not found")
                return
            title.update(f"Group  x{group.count}")
            body.update(
                f"title: {group.title}\n"
                f"fingerprint: {group.fingerprint}\n"
                f"first_seen: {group.first_seen.isoformat()}\n"
                f"last_seen: {group.last_seen.isoformat()}\n"
                f"examples: {list(group.example_ids)}"
                f"{corr_block}"
            )
            return

        if ref.kind == "item" and ref.item_id is not None:
            item = session.get_item(ref.item_id)
            if item is None:
                self.show_placeholder("Item not found")
                return
            title.update(f"Item  {item.key}")
            body.update(
                f"key: {item.key}\n"
                f"stage: {item.stage or '(none)'}\n"
                f"status: {item.status.value}\n"
                f"attempts: {item.attempts}\n"
                f"run_id: {item.run_id}\n"
                f"item_id: {item.id}"
            )
            return

        if ref.kind == "error" and ref.error_id is not None:
            err = session.get_error(ref.error_id)
            if err is None:
                self.show_placeholder("Error not found")
                return
            self._show_error(title, body, err, correlation=correlation)
            return

        self.show_placeholder()

    def _show_error(
        self,
        title: Label,
        body: Static,
        err: ErrorRecord,
        *,
        correlation: Optional[CorrelationReport] = None,
    ) -> None:
        title.update(f"{err.exc_type}")
        tb = err.traceback or "(no traceback)"
        gate = err.gate.value if err.gate else "-"
        body.update(
            f"type: {err.exc_type}\n"
            f"message: {err.message}\n"
            f"normalized: {err.normalized_message}\n"
            f"fingerprint: {err.fingerprint}\n"
            f"gate: {gate}  (OR=any child / AND=all children)\n"
            f"depth: {err.depth}  group_root: {err.is_group_root}\n"
            f"parent_error_id: {err.parent_error_id}\n"
            f"ts: {err.ts.isoformat()}\n"
            f"{format_correlation_panel(correlation)}"
            f"\n--- traceback ---\n{tb}"
        )


def format_group_label(group: Group, *, pct: float | None = None) -> str:
    title = group.title if len(group.title) <= 60 else group.title[:57] + "..."
    if pct is None:
        return f"x{group.count}  {title}"
    return f"{pct:5.1f}%  x{group.count}  {title}"


def format_item_label(item: Item) -> str:
    stage = item.stage or "-"
    return f"[{item.status.value}] {item.key} @ {stage}"


def format_error_label(err: ErrorRecord) -> str:
    msg = err.message if len(err.message) <= 60 else err.message[:57] + "..."
    mark = "*" if err.is_group_root else " "
    gate = f"[{err.gate.value}] " if err.gate else ""
    return f"{mark}{gate}{err.exc_type}: {msg}"


def format_diff_label(
    *,
    before_count: int,
    after_count: int,
    title: str,
) -> str:
    short = title if len(title) <= 55 else title[:52] + "..."
    return f"{before_count} -> {after_count}  {short}"


def format_correlation_panel(report: Optional[CorrelationReport]) -> str:
    """Plain-text 'Likely related change' block for the detail panel."""
    if report is None:
        return ""
    lines = [
        "",
        "--- Likely related change (correlation, not proof) ---",
        f"runs: {report.before_run_id} -> {report.after_run_id}",
        f"versions: {report.before_version or '-'} -> {report.after_version or '-'}",
        f"{report.message}",
    ]
    if not report.changes:
        return "\n".join(lines) + "\n"
    top = report.changes[0]
    lines.append(f"top: [{top.confidence}] {top.rank.value}  {top.path}")
    if top.function:
        lines.append(f"function: {top.function}")
    lines.append(f"note: {top.note}")
    if top.unified_diff:
        lines.append("--- diff ---")
        # Keep the panel readable.
        for dline in top.unified_diff.splitlines()[:40]:
            lines.append(dline)
    return "\n".join(lines) + "\n"
