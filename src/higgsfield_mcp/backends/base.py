"""Backend abstraction.

Both backends submit a job and return a ``JobHandle`` that can be polled or
cancelled. The handle is opaque to callers but always carries enough info to
re-target the right backend on subsequent calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from higgsfield_mcp.models import Backend as BackendName
from higgsfield_mcp.models import ModelSpec

JobState = Literal["queued", "in_progress", "completed", "failed", "nsfw", "cancelled"]


@dataclass(frozen=True)
class JobHandle:
    backend: BackendName
    request_id: str
    """Backend-native ID. Encoded as ``{backend}:{request_id}`` when serialised."""

    @classmethod
    def parse(cls, serialised: str) -> JobHandle:
        if ":" not in serialised:
            raise ValueError(f"Invalid job handle: {serialised!r}")
        backend, request_id = serialised.split(":", 1)
        if backend not in ("official", "web"):
            raise ValueError(f"Unknown backend in handle: {backend!r}")
        return cls(backend=backend, request_id=request_id)  # type: ignore[arg-type]

    def serialise(self) -> str:
        return f"{self.backend}:{self.request_id}"


@dataclass(frozen=True)
class JobStatus:
    state: JobState
    progress: float | None = None
    images: tuple[str, ...] = ()
    video_url: str | None = None
    error: str | None = None
    raw: dict[str, Any] | None = None


class BackendDriver(Protocol):
    """Backend ABC. Implementations live in ``official.py`` / ``web.py``."""

    name: BackendName

    async def submit(self, model: ModelSpec, params: dict[str, Any]) -> JobHandle: ...
    async def status(self, handle: JobHandle) -> JobStatus: ...
    async def cancel(self, handle: JobHandle) -> None: ...
    async def upload(self, data: bytes, mime: str) -> str: ...
    async def aclose(self) -> None: ...


class BackendError(RuntimeError):
    """Wraps backend HTTP errors with a human-readable message."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
