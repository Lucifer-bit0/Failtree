"""Textual TUI: group → item → error tree with detail panel."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Select, Tree
from textual.widgets.tree import TreeNode

from failtree.viewer.loading import BrowserSession, NodeRef, open_sessions
from failtree.viewer.widgets import (
    DetailPanel,
    SummaryHeader,
    format_error_label,
    format_group_label,
    format_item_label,
)


class FailtreeApp(App[None]):
    """Browse one or more failtree SQLite databases."""

    TITLE = "failtree"
    CSS = """
    Screen {
        layout: vertical;
    }
    #toolbar {
        height: auto;
        padding: 0 1;
    }
    #body {
        height: 1fr;
    }
    #tree {
        width: 1fr;
        min-width: 30;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "focus_search", "Search"),
        Binding("f", "cycle_stage", "Stage filter"),
        Binding("e", "export_failed", "Export"),
        Binding("d", "focus_db", "Switch DB"),
    ]

    def __init__(
        self,
        db_paths: Sequence[Path],
        *,
        run_id: Optional[int] = None,
    ) -> None:
        super().__init__()
        paths = [Path(p) for p in db_paths]
        if not paths:
            raise ValueError("At least one database path is required")
        self._paths = paths
        self._sessions: List[BrowserSession] = open_sessions(paths)
        self._session_index = 0
        self._run_id = run_id
        self._search = ""
        self._stage = ""
        self._stages = ["", "download", "parse", "boot", "logging", "capture"]

    @property
    def session(self) -> BrowserSession:
        return self._sessions[self._session_index]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="toolbar"):
            yield SummaryHeader(id="summary")
            options = [(str(p), i) for i, p in enumerate(self._paths)]
            yield Select(
                options,
                value=0,
                id="db-select",
                prompt="Database",
                allow_blank=False,
            )
            yield Input(placeholder="Search groups (/)", id="search")
        with Horizontal(id="body"):
            yield Tree("Groups", id="tree")
            yield DetailPanel(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._reload_tree()
        self._refresh_header()
        self.set_interval(2.0, self._refresh_header)

    def on_unmount(self) -> None:
        for session in self._sessions:
            session.close()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_focus_db(self) -> None:
        self.query_one("#db-select", Select).focus()

    def action_refresh(self) -> None:
        self._reload_tree()
        self._refresh_header()
        self.notify("Refreshed")

    def action_cycle_stage(self) -> None:
        try:
            idx = self._stages.index(self._stage)
        except ValueError:
            idx = 0
        self._stage = self._stages[(idx + 1) % len(self._stages)]
        self._reload_tree()
        self._refresh_header()
        label = self._stage or "(all stages)"
        self.notify(f"Stage filter: {label}")

    def action_export_failed(self) -> None:
        dest = Path("retry.txt")
        n = self.session.export_failed(
            dest, run_id=self._run_id, stage=self._stage or None
        )
        self.notify(f"Wrote {n} keys to {dest}")

    @on(Select.Changed, "#db-select")
    def _db_changed(self, event: Select.Changed) -> None:
        if event.value is Select.NULL:
            return
        self._session_index = int(event.value)
        self._run_id = None
        self._reload_tree()
        self._refresh_header()

    @on(Input.Submitted, "#search")
    def _search_submitted(self, event: Input.Submitted) -> None:
        self._search = event.value.strip()
        self._reload_tree()
        self._refresh_header()

    @on(Tree.NodeExpanded, "#tree")
    def _node_expanded(self, event: Tree.NodeExpanded[NodeRef]) -> None:
        node = event.node
        ref = node.data
        if ref is None or ref.loaded:
            return
        if ref.kind == "group" and ref.fingerprint:
            self._load_group_children(node, ref.fingerprint)
        elif ref.kind == "item" and ref.item_id is not None:
            self._load_item_children(node, ref.item_id)
        elif ref.kind == "error" and ref.error_id is not None:
            self._load_error_children(node, ref.error_id)
        ref.loaded = True
        node.data = ref

    @on(Tree.NodeHighlighted, "#tree")
    def _node_highlighted(self, event: Tree.NodeHighlighted[NodeRef]) -> None:
        ref = event.node.data
        detail = self.query_one(DetailPanel)
        if ref is None:
            detail.show_placeholder()
            return
        detail.show_node(self.session, ref)

    def _refresh_header(self) -> None:
        header = self.query_one(SummaryHeader)
        header.show(
            db_label=str(self.session.path.name),
            summary=self.session.summary(self._run_id),
            filter_text=self._search,
            stage=self._stage,
        )

    def _reload_tree(self) -> None:
        tree = self.query_one("#tree", Tree)
        tree.clear()
        tree.root.expand()
        groups = self.session.list_groups(query=self._search or None)
        if not groups:
            tree.root.add_leaf("(no groups)")
            self.query_one(DetailPanel).show_placeholder("No groups")
            return
        for group in groups:
            ref = NodeRef(kind="group", fingerprint=group.fingerprint)
            node = tree.root.add(
                format_group_label(group),
                data=ref,
                allow_expand=True,
            )
            # Placeholder child so the expand affordance appears.
            node.add_leaf("…")

    def _load_group_children(self, node: TreeNode[NodeRef], fingerprint: str) -> None:
        node.remove_children()
        items = self.session.list_items_for_group(
            fingerprint,
            run_id=self._run_id,
            stage=self._stage or None,
        )
        if not items:
            node.add_leaf("(no items)")
            return
        for item in items:
            child = node.add(
                format_item_label(item),
                data=NodeRef(kind="item", item_id=item.id, fingerprint=fingerprint),
                allow_expand=True,
            )
            child.add_leaf("…")

    def _load_item_children(self, node: TreeNode[NodeRef], item_id: int) -> None:
        node.remove_children()
        roots = self.session.list_root_errors(item_id)
        if not roots:
            node.add_leaf("(no errors)")
            return
        for err in roots:
            child = node.add(
                format_error_label(err),
                data=NodeRef(kind="error", error_id=err.id, item_id=item_id),
                allow_expand=True,
            )
            # Always allow expand; load real children on expand.
            child.add_leaf("…")

    def _load_error_children(self, node: TreeNode[NodeRef], error_id: int) -> None:
        node.remove_children()
        children = self.session.list_child_errors(error_id)
        if not children:
            node.add_leaf("(leaf)")
            return
        for err in children:
            child = node.add(
                format_error_label(err),
                data=NodeRef(kind="error", error_id=err.id, item_id=err.item_id),
                allow_expand=True,
            )
            child.add_leaf("…")


def run_viewer(
    db_paths: Sequence[str | Path],
    *,
    run_id: Optional[int] = None,
) -> None:
    """Launch the Textual app (blocking)."""
    paths = [Path(p) for p in db_paths]
    FailtreeApp(paths, run_id=run_id).run()
