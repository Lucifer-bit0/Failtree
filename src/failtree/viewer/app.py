"""Textual TUI: group → item → error tree with detail panel + run diff."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Select, Tree
from textual.widgets.tree import TreeNode

from failtree.core.models import CorrelationReport, DiffKind, RunDiff
from failtree.viewer.loading import BrowserSession, NodeRef, open_sessions
from failtree.viewer.widgets import (
    DetailPanel,
    SummaryHeader,
    format_diff_label,
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
        Binding("c", "toggle_diff", "Diff"),
    ]

    def __init__(
        self,
        db_paths: Sequence[Path],
        *,
        run_id: Optional[int] = None,
        diff_before: Optional[int] = None,
        diff_after: Optional[int] = None,
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
        self._diff_mode = diff_before is not None and diff_after is not None
        self._diff_before = diff_before
        self._diff_after = diff_after
        self._cached_diff: Optional[RunDiff] = None

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
        self._cached_diff = None
        self._reload_tree()
        self._refresh_header()
        self.notify("Refreshed")

    def action_toggle_diff(self) -> None:
        if self._diff_mode:
            self._diff_mode = False
            self._cached_diff = None
            self._reload_tree()
            self._refresh_header()
            self.notify("Browse mode")
            return
        pair = None
        if self._diff_before is not None and self._diff_after is not None:
            pair = (self._diff_before, self._diff_after)
        else:
            pair = self.session.default_diff_pair()
        if pair is None:
            self.notify("Need at least two runs to diff")
            return
        self._diff_before, self._diff_after = pair
        self._diff_mode = True
        self._cached_diff = None
        self._reload_tree()
        self._refresh_header()
        self.notify(f"Diff run {self._diff_before} -> {self._diff_after}")

    def action_cycle_stage(self) -> None:
        if self._diff_mode:
            self.notify("Stage filter disabled in diff mode")
            return
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
        self._cached_diff = None
        if self._diff_mode:
            pair = self.session.default_diff_pair()
            if pair is None:
                self._diff_mode = False
                self._diff_before = self._diff_after = None
            else:
                self._diff_before, self._diff_after = pair
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
        fingerprint = ref.fingerprint if ref.kind in ("group", "diff_row") else None
        if ref.kind == "error" and ref.error_id is not None:
            err = self.session.get_error(ref.error_id)
            if err is not None:
                fingerprint = err.fingerprint
        detail.show_node(
            self.session,
            ref,
            correlation=self._correlation_for(fingerprint),
        )

    def _correlation_for(
        self, fingerprint: Optional[str]
    ) -> Optional[CorrelationReport]:
        """Best-effort correlation vs previous run (or active diff pair)."""
        before = after = None
        if self._diff_mode and self._diff_before and self._diff_after:
            before, after = self._diff_before, self._diff_after
        else:
            pair = self.session.default_diff_pair()
            if pair is None:
                return None
            before, after = pair
        try:
            return self.session.correlate_runs(
                before, after, fingerprint=fingerprint
            )
        except ValueError:
            return None

    def _current_diff(self) -> Optional[RunDiff]:
        if not self._diff_mode:
            return None
        if self._diff_before is None or self._diff_after is None:
            return None
        if self._cached_diff is None:
            try:
                self._cached_diff = self.session.compare_runs(
                    self._diff_before, self._diff_after
                )
            except ValueError:
                return None
        return self._cached_diff

    def _refresh_header(self) -> None:
        header = self.query_one(SummaryHeader)
        header.show(
            db_label=str(self.session.path.name),
            summary=self.session.summary(self._run_id),
            filter_text=self._search,
            stage=self._stage,
            diff=self._current_diff(),
        )

    def _reload_tree(self) -> None:
        if self._diff_mode:
            self._reload_diff_tree()
            return
        tree = self.query_one("#tree", Tree)
        tree.clear()
        tree.root.set_label("Groups")
        tree.root.expand()
        groups = self.session.list_groups(query=self._search or None)
        if not groups:
            tree.root.add_leaf("(no groups)")
            self.query_one(DetailPanel).show_placeholder("No groups")
            return
        impacts = {
            i.fingerprint: i.pct_of_failures
            for i in self.session.rank_groups(run_id=self._run_id)
        }
        for group in groups:
            ref = NodeRef(kind="group", fingerprint=group.fingerprint)
            node = tree.root.add(
                format_group_label(group, pct=impacts.get(group.fingerprint)),
                data=ref,
                allow_expand=True,
            )
            # Placeholder child so the expand affordance appears.
            node.add_leaf("...")

    def _reload_diff_tree(self) -> None:
        tree = self.query_one("#tree", Tree)
        tree.clear()
        diff = self._current_diff()
        if diff is None:
            tree.root.set_label("Diff")
            tree.root.expand()
            tree.root.add_leaf("(unable to compare runs)")
            return
        tree.root.set_label(f"Diff {diff.before_run_id} -> {diff.after_run_id}")
        tree.root.expand()
        q = (self._search or "").lower()
        sections = [
            (DiffKind.NEW, "NEW", diff.new),
            (DiffKind.FIXED, "FIXED", diff.fixed),
            (DiffKind.PERSISTING, "PERSISTING", diff.persisting),
            (DiffKind.REGRESSED, "REGRESSED", diff.regressed),
        ]
        any_rows = False
        for kind, label, rows in sections:
            filtered = [
                r
                for r in rows
                if not q
                or q in r.title.lower()
                or q in r.fingerprint.lower()
                or q in kind.value
            ]
            section = tree.root.add(
                f"{label} ({len(filtered)})",
                data=NodeRef(kind="diff_section", diff_kind=kind.value, loaded=True),
                allow_expand=True,
            )
            section.expand()
            if not filtered:
                section.add_leaf("(none)")
                continue
            any_rows = True
            for row in filtered:
                section.add_leaf(
                    format_diff_label(
                        before_count=row.before_count,
                        after_count=row.after_count,
                        title=row.title,
                    ),
                    data=NodeRef(
                        kind="diff_row",
                        fingerprint=row.fingerprint,
                        diff_kind=row.kind.value,
                        before_count=row.before_count,
                        after_count=row.after_count,
                        title=row.title,
                        loaded=True,
                    ),
                )
        if not any_rows and not q:
            self.query_one(DetailPanel).show_placeholder("No fingerprint changes")

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
            child.add_leaf("...")

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
            child.add_leaf("...")

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
            child.add_leaf("...")


def run_viewer(
    db_paths: Sequence[str | Path],
    *,
    run_id: Optional[int] = None,
    diff_before: Optional[int] = None,
    diff_after: Optional[int] = None,
) -> None:
    """Launch the Textual app (blocking)."""
    paths = [Path(p) for p in db_paths]
    FailtreeApp(
        paths,
        run_id=run_id,
        diff_before=diff_before,
        diff_after=diff_after,
    ).run()
