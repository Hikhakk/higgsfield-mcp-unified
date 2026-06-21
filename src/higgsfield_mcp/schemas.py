"""Pydantic output models for the MCP tools.

FastMCP turns a tool's Pydantic return annotation into the MCP ``outputSchema``
and emits ``structuredContent``. The ``tools.py`` functions still return plain
dicts; the ``server.py`` wrappers validate those dicts into these models.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ModelInfo(BaseModel):
    id: str
    label: str
    kind: str
    backend: str
    endpoint: str
    supports: list[str]
    constraints: list[str] = []
    confidence: str = "verified"
    notes: str = ""


class ModelList(BaseModel):
    count: int
    models: list[ModelInfo]


class SubmitResult(BaseModel):
    job_handle: str
    model_id: str
    backend: str


class JobStatusResult(BaseModel):
    job_handle: str
    state: str
    progress: float | None = None
    images: list[str] = []
    video_url: str | None = None
    error: str | None = None
    timeout: bool = False


class CancelResult(BaseModel):
    cancelled: bool
    job_handle: str


class UploadResult(BaseModel):
    url: str
    backend: str


class OfficialHealth(BaseModel):
    configured: bool
    ok: bool
    error: str | None = None


class WebHealth(BaseModel):
    enabled: bool
    ok: bool
    error: str | None = None


class PreflightResult(BaseModel):
    official: OfficialHealth
    web: WebHealth


class RecommendItem(BaseModel):
    model_id: str
    label: str
    kind: str
    backend: str
    score: int
    why: str


class RecommendResult(BaseModel):
    intent: str
    recommendations: list[RecommendItem]


class ValidateResult(BaseModel):
    model_id: str
    known_model: bool
    valid: bool
    unsupported: list[str]
    supported: list[str]
    constraints: list[str]


class Character(BaseModel):
    id: str
    name: str
    status: str
    image_count: int
    raw: dict[str, Any] = {}


class CharacterList(BaseModel):
    count: int
    characters: list[Character]


class CharacterDeleted(BaseModel):
    deleted: bool
    character_id: str


class Balance(BaseModel):
    credits: int | None = None
    plan: str | None = None
    raw: dict[str, Any] = {}


class JobList(BaseModel):
    count: int
    jobs: list[dict[str, Any]]


class NameList(BaseModel):
    count: int
    names: list[str]
    raw: dict[str, Any] = {}
