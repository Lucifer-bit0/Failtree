"""Textual widgets for header + detail panel."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from failtree.core.models import ErrorRecord, Group, Item, RunSummary
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
    ) -> None:
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
            f"groups={summary.groups}  recovered={summary.recovered}{filt}"
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

    def show_node(self, session: BrowserSession, ref: NodeRef) -> None:
        title = self.query_one("#detail-title", Label)
        body = self.query_one("#detail-body", Static)

        if ref.kind == "group" and ref.fingerprint:
            group = session.get_group(ref.fingerprint)
            if group is None:
                self.show_placeholder("Group not found")
                return
            title.update(f"Group  ×{group.count}")
            body.update(
                f"title: {group.title}\n"
                f"fingerprint: {group.fingerprint}\n"
                f"first_seen: {group.first_seen.isoformat()}\n"
                f"last_seen: {group.last_seen.isoformat()}\n"
                f"examples: {list(group.example_ids)}"
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
            self._show_error(title, body, err)
            return

        self.show_placeholder()

    def _show_error(self, title: Label, body: Static, err: ErrorRecord) -> None:
        title.update(f"{err.exc_type}")
        tb = err.traceback or "(no traceback)"
        body.update(
            f"type: {err.exc_type}\n"
            f"message: {err.message}\n"
            f"normalized: {err.normalized_message}\n"
            f"fingerprint: {err.fingerprint}\n"
            f"depth: {err.depth}  group_root: {err.is_group_root}\n"
            f"parent_error_id: {err.parent_error_id}\n"
            f"ts: {err.ts.isoformat()}\n"
            f"\n--- traceback ---\n{tb}"
        )


def format_group_label(group: Group) -> str:
    title = group.title if len(group.title) <= 72 else group.title[:69] + "..."
    return f"×{group.count}  {title}"


def format_item_label(item: Item) -> str:
    stage = item.stage or "-"
    return f"[{item.status.value}] {item.key} @ {stage}"


def format_error_label(err: ErrorRecord) -> str:
    msg = err.message if len(err.message) <= 60 else err.message[:57] + "..."
    mark = "*" if err.is_group_root else " "
    return f"{mark}{err.exc_type}: {msg}"
