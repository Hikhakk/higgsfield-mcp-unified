from __future__ import annotations

from higgsfield_mcp.schemas import (
    JobStatusResult,
    ModelList,
    PreflightResult,
    SubmitResult,
)


def test_modellist_validates_registry_dict() -> None:
    raw = {
        "count": 1,
        "models": [
            {
                "id": "higgsfield-ai/soul/standard",
                "label": "Soul",
                "kind": "image",
                "backend": "official",
                "endpoint": "higgsfield-ai/soul/standard",
                "supports": ("prompt", "aspect_ratio"),  # tuple coerces to list
                "constraints": (),
                "confidence": "verified",
                "notes": "",
            }
        ],
    }
    parsed = ModelList.model_validate(raw)
    assert parsed.count == 1
    assert parsed.models[0].supports == ["prompt", "aspect_ratio"]


def test_submit_result() -> None:
    s = SubmitResult.model_validate(
        {"job_handle": "official:abc", "model_id": "m", "backend": "official"}
    )
    assert s.job_handle == "official:abc"


def test_job_status_defaults_timeout_false() -> None:
    s = JobStatusResult.model_validate(
        {
            "job_handle": "web:1",
            "state": "queued",
            "progress": None,
            "images": [],
            "video_url": None,
            "error": None,
        }
    )
    assert s.timeout is False


def test_job_status_timeout_true() -> None:
    s = JobStatusResult.model_validate(
        {
            "job_handle": "web:1",
            "state": "in_progress",
            "progress": None,
            "images": [],
            "video_url": None,
            "error": None,
            "timeout": True,
        }
    )
    assert s.timeout is True


def test_preflight_result_nested() -> None:
    p = PreflightResult.model_validate(
        {
            "official": {"configured": True, "ok": True, "error": None},
            "web": {"enabled": False, "ok": False, "error": "disabled"},
        }
    )
    assert p.official.configured is True
    assert p.web.enabled is False
    assert p.web.error == "disabled"
