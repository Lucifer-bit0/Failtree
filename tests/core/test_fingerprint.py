from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from failtree.core.fingerprint import FingerprintConfig, Fingerprinter, MessageNormalizer
from failtree.core.models import StackFrame

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "messy_errors.json"


def test_message_normalizer_strips_volatiles() -> None:
    norm = MessageNormalizer(FingerprintConfig())
    out = norm.normalize(
        "id 550e8400-e29b-41d4-a716-446655440000 at /tmp/a.csv row 12 user 'x'"
    )
    assert "<UUID>" in out
    assert "<PATH>" in out
    assert "<NUM>" in out
    assert "<STR>" in out
    assert "550e8400" not in out


def test_same_bug_different_line_same_fingerprint() -> None:
    fp = Fingerprinter(FingerprintConfig(project_roots=(Path("/proj"),)))
    a = fp.fingerprint(
        "ValueError",
        "bad id 550e8400-e29b-41d4-a716-446655440000",
        [StackFrame("/proj/pipeline/parse.py", "parse_row", 10)],
    )
    b = fp.fingerprint(
        "ValueError",
        "bad id 123e4567-e89b-12d3-a456-426614174000",
        [StackFrame("/proj/pipeline/parse.py", "parse_row", 99)],
    )
    assert a.fingerprint == b.fingerprint


def test_golden_fixture_partition() -> None:
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    fp = Fingerprinter(FingerprintConfig(project_roots=(Path("/proj"),)))

    by_group: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        frames = [StackFrame(**f) for f in case["frames"]]
        result = fp.fingerprint(case["exc_type"], case["message"], frames)
        by_group[case["expect_group"]].add(result.fingerprint)

    # Each logical group collapses to exactly one fingerprint.
    for group, fingerprints in by_group.items():
        assert len(fingerprints) == 1, f"{group} split into {fingerprints}"

    # Distinct logical groups stay distinct.
    unique = {next(iter(v)) for v in by_group.values()}
    assert len(unique) == len(by_group)
