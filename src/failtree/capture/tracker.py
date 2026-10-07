"""User-facing Tracker API for zero-config pipeline capture."""

from __future__ import annotations

import functools
import inspect
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Pattern, Sequence, TypeVar

from failtree.capture.chains import (
    extract_frames,
    format_exception_text,
    leaf_indices,
    walk_exception,
)
from failtree.capture.concurrency import write_with_retry
from failtree.capture.code_version import detect_code_version
from failtree.capture.redaction import compile_extra_patterns, redact_text
from failtree.capture.snapshot import snapshot_frames
from failtree.common.timeutil import utc_now_iso
from failtree.core.fingerprint import FingerprintConfig, Fingerprinter
from failtree.core.models import ItemStatus, NewError, RunStatus, RunSummary, StackFrame
from failtree.core.sink import ErrorSink, SqliteSink

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class ItemHandle:
    """Handle yielded by :meth:`Tracker.item` (key/stage for user code)."""

    item_id: int
    key: str
    stage: str
    gate: Optional[str] = None  # optional OR/AND marker for root errors


class Tracker:
    """Capture per-item outcomes via an :class:`ErrorSink` (SQLite by default).

    **Fail-open:** persistence problems are logged to stderr and never crash
    the host application. User exceptions still propagate unless
    ``continue_on_error=True``.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        sink: ErrorSink | None = None,
        label: Optional[str] = None,
        project_roots: Sequence[str | Path] | None = None,
        continue_on_error: bool = False,
        fingerprint_config: Optional[FingerprintConfig] = None,
        meta: Optional[Dict[str, Any]] = None,
        sample_cap: int = 5,
        redact: bool = True,
        extra_redact_patterns: Sequence[tuple[str, str]] = (),
        heartbeat_interval: float = 0.0,
    ) -> None:
        if sink is None:
            if db_path is None:
                raise ValueError("Provide db_path or sink")
            sink = SqliteSink(db_path)
        elif db_path is not None:
            raise ValueError("Pass only one of db_path or sink")

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
        self._project_roots = tuple(Path(p) for p in fingerprint_config.project_roots)
        self._sink = sink
        self._sample_cap = sample_cap
        self._redact = redact
        self._redact_patterns: tuple[tuple[Pattern[str], str], ...] = (
            compile_extra_patterns(extra_redact_patterns)
        )
        self._closed = False
        self._run_id = 0
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

        code = detect_code_version(project_roots=self._project_roots)
        run_meta = dict(meta or {})
        run_meta.setdefault("code_version", code.version)
        run_meta.setdefault("code_version_source", code.source)

        run_id = self._safe(
            lambda: write_with_retry(
                lambda: self._sink.start_run(
                    label=label,
                    meta=run_meta,
                    code_version=code.version,
                    code_version_source=code.source,
                )
            )
        )
        self._run_id = int(run_id or 0)

        if heartbeat_interval and heartbeat_interval > 0 and self._run_id:
            self._start_heartbeat(heartbeat_interval)

    @property
    def run_id(self) -> int:
        return self._run_id

    @property
    def sink(self) -> ErrorSink:
        return self._sink

    @property
    def storage(self) -> Any:
        """Backward-compatible access to underlying Storage when using SqliteSink."""
        storage = getattr(self._sink, "storage", None)
        if storage is None:
            raise AttributeError("This sink has no .storage attribute")
        return storage

    def __enter__(self) -> "Tracker":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        status = RunStatus.ABORTED if exc_type is not None else RunStatus.COMPLETED
        self.close(status=status)

    def close(self, *, status: RunStatus = RunStatus.COMPLETED) -> None:
        if self._closed:
            return
        self._closed = True
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=1.0)
            self._heartbeat_thread = None
        if self._run_id:
            self._safe(
                lambda: write_with_retry(
                    lambda: self._sink.finish_run(self._run_id, status)
                )
            )
        self._safe(self._sink.close)

    def summary(self) -> RunSummary:
        empty = RunSummary(
            run_id=self._run_id,
            total=0,
            ok=0,
            failed=0,
            skipped=0,
            retried=0,
            recovered=0,
            groups=0,
        )
        if not self._run_id:
            return empty
        result = self._safe(lambda: self._sink.get_summary(self._run_id))
        return result if result is not None else empty

    def heartbeat(self) -> None:
        if self._run_id and not self._closed:
            self._safe(
                lambda: write_with_retry(lambda: self._sink.heartbeat(self._run_id))
            )

    @contextmanager
    def item(
        self,
        key: str,
        *,
        stage: str = "",
        gate: Optional[str] = None,
    ) -> Iterator[ItemHandle]:
        """Track one unit of work; capture failures automatically.

        ``gate`` is an optional OR/AND marker stored on the root error when
        the item fails (batch semantics; ExceptionGroup defaults to OR).
        """
        item_id = 0
        if not self._closed and self._run_id:
            ensured = self._safe(
                lambda: write_with_retry(
                    lambda: self._sink.ensure_item(self._run_id, str(key), stage)
                )
            )
            item_id = int(ensured or 0)

        handle = ItemHandle(item_id=item_id, key=str(key), stage=stage, gate=gate)
        try:
            yield handle
        except Exception as exc:
            if item_id:
                self._persist_failure(item_id, key, stage, exc, gate=gate)
            if self.continue_on_error:
                return
            raise
        else:
            if item_id:
                self._safe(
                    lambda: write_with_retry(
                        lambda: self._sink.finalize_item(
                            self._run_id,
                            str(key),
                            stage,
                            status=ItemStatus.OK,
                            bump_attempts=True,
                        )
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

    def capture_exception(
        self,
        exc: BaseException,
        *,
        key: str = "__exception__",
        stage: str = "capture",
        gate: Optional[str] = None,
    ) -> None:
        """Record an exception outside an ``item()`` block (hooks / manual)."""
        if self._closed or not self._run_id:
            return
        item_id = self._safe(
            lambda: write_with_retry(
                lambda: self._sink.ensure_item(self._run_id, str(key), stage)
            )
        )
        if not item_id:
            return
        self._persist_failure(int(item_id), str(key), stage, exc, gate=gate)

    def _persist_failure(
        self,
        item_id: int,
        key: str,
        stage: str,
        exc: BaseException,
        *,
        gate: Optional[str] = None,
    ) -> None:
        self._safe(
            lambda: write_with_retry(
                lambda: self._sink.finalize_item(
                    self._run_id,
                    str(key),
                    stage,
                    status=ItemStatus.FAILED,
                    bump_attempts=True,
                )
            )
        )

        nodes = walk_exception(exc)
        if not nodes:
            return

        leaves = set(leaf_indices(nodes))
        ts = utc_now_iso()
        results = []
        payload: list[NewError] = []
        all_frames: list[StackFrame] = []
        for index, node in enumerate(nodes):
            frames = extract_frames(node.exc)
            all_frames.extend(frames)
            raw_message = str(node.exc)
            raw_tb = format_exception_text(node.exc)
            if self._redact:
                raw_message = redact_text(
                    raw_message, extra_patterns=self._redact_patterns
                )
                raw_tb = redact_text(raw_tb, extra_patterns=self._redact_patterns)
            result = self._fingerprinter.fingerprint(
                type(node.exc).__name__,
                raw_message,
                frames,
            )
            results.append(result)
            parent_ref: Optional[int]
            if node.parent_index is None:
                parent_ref = None
            else:
                parent_ref = -(node.parent_index + 1)
            node_gate = _infer_gate(node.exc, node.relation, gate if index == 0 else None)
            payload.append(
                NewError(
                    item_id=item_id,
                    parent_error_id=parent_ref,
                    depth=node.depth,
                    exc_type=type(node.exc).__name__,
                    message=raw_message,
                    normalized_message=result.normalized_message,
                    traceback=raw_tb,
                    fingerprint=result.fingerprint,
                    ts=ts,
                    is_group_root=index in leaves,
                    gate=node_gate,
                )
            )

        error_ids = self._safe(
            lambda: write_with_retry(lambda: self._sink.insert_errors(payload))
        )
        if not error_ids:
            return
        for index, error_id in enumerate(error_ids):
            if index not in leaves:
                continue
            result = results[index]

            def _bump(eid: int = error_id, res: Any = result) -> None:
                self._sink.bump_group(
                    fingerprint=res.fingerprint,
                    title=res.title,
                    error_id=eid,
                    ts=ts,
                    sample_cap=self._sample_cap,
                )

            self._safe(lambda: write_with_retry(_bump))

        self._snapshot_frames(all_frames)

    def _snapshot_frames(self, frames: Sequence[StackFrame]) -> None:
        if not self._run_id or not frames:
            return
        rows = snapshot_frames(frames, project_roots=self._project_roots)
        for path, content_hash, content in rows:

            def _snap(
                p: str = path, h: str = content_hash, c: str = content
            ) -> None:
                self._sink.snapshot_run_file(self._run_id, p, h, c)

            self._safe(lambda: write_with_retry(_snap))

    def _start_heartbeat(self, interval: float) -> None:
        def _loop() -> None:
            while not self._heartbeat_stop.wait(interval):
                self.heartbeat()

        self._heartbeat_thread = threading.Thread(
            target=_loop, name="failtree-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    @staticmethod
    def _safe(fn: Callable[[], Any], default: Any = None) -> Any:
        """Fail-open: never let sink failures kill the host app."""
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"failtree: {exc}", file=sys.stderr)
            return default


def _infer_gate(
    exc: BaseException,
    relation: str,
    explicit: Optional[str],
) -> Optional[str]:
    """OR for ExceptionGroup parents; honor explicit gate on the root node."""
    _ = relation
    if explicit in ("OR", "AND"):
        return explicit
    bases = {b.__name__ for b in type(exc).__mro__}
    if "BaseExceptionGroup" in bases or "ExceptionGroup" in bases:
        return "OR"
    return None


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
