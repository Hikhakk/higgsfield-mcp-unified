"""Tests for JobHandle serialisation."""

from __future__ import annotations

import pytest

from higgsfield_mcp.backends.base import JobHandle


def test_roundtrip() -> None:
    handle = JobHandle(backend="official", request_id="abc-123")
    assert JobHandle.parse(handle.serialise()) == handle


def test_parse_rejects_missing_colon() -> None:
    with pytest.raises(ValueError):
        JobHandle.parse("nope")


def test_parse_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError):
        JobHandle.parse("invalid:abc")


def test_request_id_can_contain_colons() -> None:
    handle = JobHandle.parse("web:job:42:nested")
    assert handle.backend == "web"
    assert handle.request_id == "job:42:nested"
