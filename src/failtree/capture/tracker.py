"""User-facing Tracker API for zero-config pipeline capture."""

from __future__ import annotations

import functools
import inspect
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Sequence, TypeVar

from failtree.capture.chains import (
    extract_frames,
    format_exception_text,
    leaf_indices,
    walk_exception,
)
from failtree.capture.concurrency import write_with_retry
from failtree.common.timeutil import utc_now_iso
from failtree.core.fingerprint import FingerprintConfig, Fingerprinter
from failtree.core.grouping import GroupService
from failtree.core.models import ItemStatus, NewError, RunStatus, RunSummary
from failtree.core.storage import Storage

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class ItemHandle:
    """Handle yielded by :meth:`Tracker.item` (key/stage for user code)."""

    item_id: int
    key: str
    stage: str


class Tracker:
    """Capture per-item outcomes into a local SQLite ``runs.db``.

    Typical use::

        from failtree import Tracker

        t = Tracker("runs.db", label="nightly", continue_on_error=True)
        with t:
            for path in files:
                with t.item(path, stage="parse"):
                    process(path)
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        label: Optional[str] = None,
        project_roots: Sequence[str | Path] | None = None,
        continue_on_error: bool = False,
        fingerprint_config: Optional[FingerprintConfig] = None,
        meta: Optional[Dict[str, Any]] = None,
        sample_cap: int = 5,
    ) -> None:
        roots = tuple(Path(p) for p in (project_roots or ()))
        if fingerprint_config is None:
            fingerprint_config = FingerprintConfig(project_roots=roots)
        elif roots and not fingerprint_config.project_roots:
            fingerprint_config = FingerprintConfig(
                project_roots=roots,
                top_frames=fingerprint_config.top_frames,
                strip_quoted_strings=fingerprint_config.strip_quoted_strings,
                hash_length=fingerprint_config.hash_length,
                extra_patterns=fingerprint_config.extra_patterns,
            )

        self.continue_on_error = continue_on_error
        self._fingerprinter = Fingerprinter(fingerprint_config)
        self._storage = Storage(db_path)
        self._groups = GroupService(self._storage, sample_cap=sample_cap)
        self._run_id = write_with_retry(
            lambda: self._storage.create_run(label=label, meta=meta)
        )
        self._closed = False

    @property
    def run_id(self) -> int:
        return self._run_id

    @property
    def storage(self) -> Storage:
        return self._storage

    def __enter__(self) -> "Tracker":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        status = RunStatus.ABORTED if exc_type is not None else RunStatus.COMPLETED
        self.close(status=status)

    def close(self, *, status: RunStatus = RunStatus.COMPLETED) -> None:
        if self._closed:
            return
        try:
            write_with_retry(lambda: self._storage.finish_run(self._run_id, status))
        finally:
            self._storage.close()
            self._closed = True

    def summary(self) -> RunSummary:
        return self._storage.get_summary(self._run_id)

    @contextmanager
    def item(self, key: str, *, stage: str = "") -> Iterator[ItemHandle]:
        """Track one unit of work; capture failures automatically."""
        if self._closed:
            raise RuntimeError("Tracker is closed")

        item_id = write_with_retry(
            lambda: self._storage.ensure_item(self._run_id, str(key), stage)
        )
        handle = ItemHandle(item_id=item_id, key=str(key), stage=stage)
        try:
            yield handle
        except Exception as exc:
            self._persist_failure(item_id, key, stage, exc)
            if self.continue_on_error:
                return
            raise
        else:
            write_with_retry(
                lambda: self._storage.upsert_item(
                    self._run_id,
                    str(key),
                    stage,
                    status=ItemStatus.OK,
                    bump_attempts=True,
                )
            )

    def track(
        self,
        *,
        stage: str = "",
        key_arg: str | int | None = None,
    ) -> Callable[[F], F]:
        """Decorator form of :meth:`item`."""

        def decorator(fn: F) -> F:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                key = _resolve_item_key(fn, args, kwargs, key_arg)
                with self.item(key, stage=stage):
                    return fn(*args, **kwargs)

            return wrapper  # type: ignore[return-value]

        return decorator

    def _persist_failure(
        self,
        item_id: int,
        key: str,
        stage: str,
        exc: BaseException,
    ) -> None:
        write_with_retry(
            lambda: self._storage.upsert_item(
                self._run_id,
                str(key),
                stage,
                status=ItemStatus.FAILED,
                bump_attempts=True,
            )
        )

        nodes = walk_exception(exc)
        if not nodes:
            return

        leaves = set(leaf_indices(nodes))
        ts = utc_now_iso()
        results = []
        payload: list[NewError] = []
        for index, node in enumerate(nodes):
            frames = extract_frames(node.exc)
            result = self._fingerprinter.fingerprint(
                type(node.exc).__name__,
                str(node.exc),
                frames,
            )
            results.append(result)
            parent_ref: Optional[int]
            if node.parent_index is None:
                parent_ref = None
            else:
                parent_ref = -(node.parent_index + 1)
            payload.append(
                NewError(
                    item_id=item_id,
                    parent_error_id=parent_ref,
                    depth=node.depth,
                    exc_type=type(node.exc).__name__,
                    message=str(node.exc),
                    normalized_message=result.normalized_message,
                    traceback=format_exception_text(node.exc),
                    fingerprint=result.fingerprint,
                    ts=ts,
                    is_group_root=index in leaves,
                )
            )

        error_ids = write_with_retry(lambda: self._storage.insert_errors(payload))
        for index, error_id in enumerate(error_ids):
            if index not in leaves:
                continue
            result = results[index]

            def _bump(eid: int = error_id, res: Any = result) -> None:
                self._groups.bump(
                    fingerprint=res.fingerprint,
                    title=res.title,
                    error_id=eid,
                    ts=ts,
                )

            write_with_retry(_bump)


def _resolve_item_key(
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: Dict[str, Any],
    key_arg: str | int | None,
) -> str:
    """Resolve the item key for a decorated function call."""
    if isinstance(key_arg, int):
        if key_arg < len(args):
            return str(args[key_arg])
        raise TypeError(f"key_arg index {key_arg} out of range for {fn.__name__}")

    if isinstance(key_arg, str):
        if key_arg in kwargs:
            return str(kwargs[key_arg])
        params = list(inspect.signature(fn).parameters)
        if key_arg in params:
            idx = params.index(key_arg)
            if idx < len(args):
                return str(args[idx])
        raise TypeError(f"key_arg '{key_arg}' not found for {fn.__name__}")

    if args:
        return str(args[0])
    if kwargs:
        return str(next(iter(kwargs.values())))
    return fn.__name__
