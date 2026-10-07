from __future__ import annotations

from pathlib import Path

import failtree
from failtree.capture.redaction import redact_text


def test_redact_api_key() -> None:
    text = "Authorization: Bearer abcdef0123456789secret"
    out = redact_text(text)
    assert "abcdef0123456789secret" not in out
    assert "REDACTED" in out


def test_init_and_get_tracker(tmp_path: Path) -> None:
    db = tmp_path / "runs.db"
    t = failtree.init(db, label="svc", install_process_hooks=False, heartbeat_interval=0)
    assert failtree.get_tracker() is t
    with t.item("x", stage="work"):
        pass
    summary = t.summary()
    assert summary.ok == 1
    failtree.shutdown()


def test_capture_exception_redacts(tmp_path: Path) -> None:
    with failtree.Tracker(tmp_path / "runs.db", continue_on_error=True) as t:
        try:
            raise ValueError("password=super-secret-value")
        except ValueError as exc:
            t.capture_exception(exc, key="manual", stage="test")
        errors = t.storage.list_errors_for_item(
            t.storage.ensure_item(t.run_id, "manual", "test")
        )
        assert errors
        assert "super-secret-value" not in errors[0].message
        assert "REDACTED" in errors[0].message
