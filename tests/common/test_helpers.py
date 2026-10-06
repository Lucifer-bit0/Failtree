from __future__ import annotations

import pytest

from failtree.common.hashing import short_sha256
from failtree.common.jsonutil import dumps_json, loads_json
from failtree.common.timeutil import parse_iso, utc_now_iso


def test_short_sha256_length_and_stability() -> None:
    a = short_sha256("hello", length=16)
    b = short_sha256("hello", length=16)
    assert a == b
    assert len(a) == 16
    assert a != short_sha256("world", length=16)


def test_short_sha256_rejects_bad_length() -> None:
    with pytest.raises(ValueError):
        short_sha256("x", length=0)


def test_json_roundtrip() -> None:
    payload = {"a": 1, "b": [1, 2]}
    text = dumps_json(payload)
    assert loads_json(text) == payload


def test_loads_json_default() -> None:
    assert loads_json("", default=[]) == []
    assert loads_json("not-json", default={}) == {}


def test_utc_iso_roundtrip() -> None:
    stamp = utc_now_iso()
    dt = parse_iso(stamp)
    assert dt.tzinfo is not None
    assert stamp.endswith("Z")
