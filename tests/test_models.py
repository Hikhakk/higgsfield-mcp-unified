"""Registry shape and integrity tests."""

from __future__ import annotations

import pytest

from higgsfield_mcp.models import REGISTRY, UnknownModelError


def test_registry_has_all_known_models() -> None:
    assert len(REGISTRY.by_id) == 27, "expected 8 official + 19 web"


def test_no_duplicate_ids() -> None:
    ids = list(REGISTRY.by_id.keys())
    assert len(ids) == len(set(ids))


def test_split_by_backend() -> None:
    official = REGISTRY.list(backend="official")
    web = REGISTRY.list(backend="web", include_unverified=True)
    assert len(official) == 8
    assert len(web) == 19


def test_split_by_kind() -> None:
    images = REGISTRY.list(kind="image", include_unverified=True)
    videos = REGISTRY.list(kind="video", include_unverified=True)
    assert len(images) == 8
    assert len(videos) == 19


def test_inferred_hidden_by_default() -> None:
    assert any(s.confidence == "inferred" for s in REGISTRY.by_id.values())
    assert all(s.confidence == "verified" for s in REGISTRY.list())


def test_known_model_lookup() -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    assert spec.kind == "image"
    assert spec.backend == "official"


def test_unknown_model_raises() -> None:
    with pytest.raises(UnknownModelError):
        REGISTRY.get("not-a-real-model")


def test_official_endpoint_format() -> None:
    """Official endpoints are vendor/model[/...] paths, not absolute URLs."""
    for spec in REGISTRY.list(backend="official"):
        assert "://" not in spec.endpoint
        assert spec.endpoint == spec.id  # by convention; id == path on platform.higgsfield.ai


def test_web_endpoint_format() -> None:
    """Web endpoints start with /jobs."""
    for spec in REGISTRY.list(backend="web", include_unverified=True):
        assert spec.endpoint.startswith("/jobs")


def test_modelspec_is_frozen() -> None:
    spec = next(iter(REGISTRY.by_id.values()))
    with pytest.raises((AttributeError, Exception)):
        spec.id = "mutated"  # type: ignore[misc]
