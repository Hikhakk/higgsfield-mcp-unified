"""Registry shape and integrity tests."""

from __future__ import annotations

import pytest

from higgsfield_mcp.models import REGISTRY, UnknownModelError


def test_registry_has_all_known_models() -> None:
    assert len(REGISTRY.by_id) == 119, "expected 85 official + 34 web"


def test_no_duplicate_ids() -> None:
    ids = list(REGISTRY.by_id.keys())
    assert len(ids) == len(set(ids))


def test_split_by_backend() -> None:
    official = REGISTRY.list(backend="official", include_unverified=True)
    web = REGISTRY.list(backend="web", include_unverified=True)
    assert len(official) == 85
    assert len(web) == 34


def test_split_by_kind() -> None:
    images = REGISTRY.list(kind="image", include_unverified=True)
    videos = REGISTRY.list(kind="video", include_unverified=True)
    assert len(images) == 30
    assert len(videos) == 89


def test_verified_default_count() -> None:
    assert len(REGISTRY.list()) == 103
    assert sum(1 for s in REGISTRY.by_id.values() if s.confidence == "inferred") == 16


def test_inferred_hidden_by_default() -> None:
    assert any(s.confidence == "inferred" for s in REGISTRY.by_id.values())
    assert all(s.confidence == "verified" for s in REGISTRY.list())


def test_known_model_lookup() -> None:
    spec = REGISTRY.get("higgsfield-ai/soul/standard")
    assert spec.kind == "image"
    assert spec.backend == "official"


def test_official_matches_docs_catalog() -> None:
    """docs.higgsfield.ai lists 84 workflows (17 image incl. Soul ID training, 67 video);
    the console additionally exposes AI Influencer and Soul 2 image-to-image."""
    official = REGISTRY.list(backend="official")
    assert sum(s.kind == "image" for s in official) == 18
    assert sum(s.kind == "video" for s in official) == 67
    console_only = {"higgsfield/ai-influencer", "higgsfield-ai/soul/v2/image-to-image"}
    for s in official:
        host = "open.higgsfield.ai/models/" if s.id in console_only else "docs.higgsfield.ai/docs/"
        assert s.notes.startswith(f"docs: https://{host}"), s.id


def test_unknown_model_raises() -> None:
    with pytest.raises(UnknownModelError):
        REGISTRY.get("not-a-real-model")


def test_official_endpoint_format() -> None:
    """Official endpoints are vendor/model[/...] paths, not absolute URLs."""
    for spec in REGISTRY.list(backend="official"):
        assert "://" not in spec.endpoint
        assert spec.endpoint == spec.id  # by convention; id == path on api.higgsfield.ai


def test_web_endpoint_format() -> None:
    """Web endpoints start with /jobs."""
    for spec in REGISTRY.list(backend="web", include_unverified=True):
        assert spec.endpoint.startswith("/jobs")


def test_modelspec_is_frozen() -> None:
    spec = next(iter(REGISTRY.by_id.values()))
    with pytest.raises((AttributeError, Exception)):
        spec.id = "mutated"  # type: ignore[misc]
