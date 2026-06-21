"""Model registry for the unified Higgsfield MCP.

Each entry maps an MCP-facing ``model_id`` to:

* the **backend** that serves it (``official`` for ``platform.higgsfield.ai`` REST
  with ``KEY:SECRET`` auth, ``web`` for ``cloud.higgsfield.ai`` with Clerk JWT),
* the **endpoint** to hit on that backend,
* the supported request parameters,
* free-form constraint notes that ``list_models`` returns to the LLM so it can
  pick reasonable defaults.

Adding a new model = one ``ModelSpec`` entry. Tests in ``tests/test_models.py``
guard registry shape and uniqueness.

Sources:

* Official IDs and endpoints: https://docs.higgsfield.ai/how-to/introduction.md,
  /guides/images.md, /guides/video.md, /how-to/sdk.md.
* Web slugs: ``jfikrat/higgsfield-mcp/src/models.ts`` (verbatim port).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Backend = Literal["official", "web"]
Kind = Literal["image", "video", "speech"]
Confidence = Literal["verified", "inferred"]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    kind: Kind
    backend: Backend
    endpoint: str
    supports: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    confidence: Confidence = "verified"
    notes: str = ""


# ---------------------------------------------------------------------------
# Official backend (platform.higgsfield.ai). Endpoint is the model_id appended
# to the base URL: POST {BASE}/{endpoint}. Auth: Authorization: Key KEY:SECRET.
# ---------------------------------------------------------------------------

_OFFICIAL: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="higgsfield-ai/soul/standard",
        label="Soul (standard)",
        kind="image",
        backend="official",
        endpoint="higgsfield-ai/soul/standard",
        supports=("prompt", "aspect_ratio", "resolution"),
        constraints=("aspect_ratio: free-form (e.g. '16:9')", "resolution: e.g. '720p'"),
    ),
    ModelSpec(
        id="reve/text-to-image",
        label="Reve text-to-image",
        kind="image",
        backend="official",
        endpoint="reve/text-to-image",
        supports=("prompt", "aspect_ratio", "resolution"),
    ),
    ModelSpec(
        id="bytedance/seedream/v4/text-to-image",
        label="Seedream v4 — text-to-image",
        kind="image",
        backend="official",
        endpoint="bytedance/seedream/v4/text-to-image",
        supports=("prompt", "aspect_ratio", "resolution"),
    ),
    ModelSpec(
        id="bytedance/seedream/v4/edit",
        label="Seedream v4 — edit",
        kind="image",
        backend="official",
        endpoint="bytedance/seedream/v4/edit",
        supports=("prompt", "image_url", "aspect_ratio", "resolution"),
    ),
    ModelSpec(
        id="higgsfield-ai/dop/preview",
        label="DOP (preview)",
        kind="video",
        backend="official",
        endpoint="higgsfield-ai/dop/preview",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="higgsfield-ai/dop/standard",
        label="DOP (standard)",
        kind="video",
        backend="official",
        endpoint="higgsfield-ai/dop/standard",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="bytedance/seedance/v1/pro/image-to-video",
        label="Seedance v1 Pro — image-to-video",
        kind="video",
        backend="official",
        endpoint="bytedance/seedance/v1/pro/image-to-video",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="kling-video/v2.1/pro/image-to-video",
        label="Kling v2.1 Pro — image-to-video",
        kind="video",
        backend="official",
        endpoint="kling-video/v2.1/pro/image-to-video",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="flux-pro/kontext/max/text-to-image",
        label="FLUX.1 Kontext Max — text-to-image",
        kind="image",
        backend="official",
        endpoint="flux-pro/kontext/max/text-to-image",
        supports=("prompt", "aspect_ratio", "seed"),
        constraints=("safety_tolerance: 0-6",),
    ),
)

# ---------------------------------------------------------------------------
# Web backend (cloud.higgsfield.ai). Endpoint is the path under the cloud host,
# auth is a Clerk JWT (Bearer header). Opt-in: HIGGSFIELD_ENABLE_WEB_BACKEND=1.
# ---------------------------------------------------------------------------

_WEB_IMAGE: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="nano-banana-2",
        label="Nano Banana 2",
        kind="image",
        backend="web",
        endpoint="/jobs/v2/nano_banana_flash",
        supports=(
            "prompt",
            "aspect_ratio",
            "batch_size",
            "enhance_prompt",
            "seed",
            "resolution",
            "input_image_urls",
        ),
        constraints=("resolution: 1k | 2k | 4k", "input_image_urls: up to 16 references"),
    ),
    ModelSpec(
        id="nano-banana-1",
        label="Nano Banana 1",
        kind="image",
        backend="web",
        # NOTE: jfikrat/higgsfield-mcp also points this slug at /jobs/nano-banana-2.
        # Likely a copy-paste bug upstream. Marked pending_verification until we
        # sniff the real path. list_models hides this by default.
        endpoint="/jobs/nano-banana-2",
        supports=(
            "prompt",
            "aspect_ratio",
            "batch_size",
            "enhance_prompt",
            "seed",
            "resolution",
            "input_image_urls",
        ),
        constraints=("resolution: 1k | 2k | 4k", "input_image_urls: up to 16 references"),
        confidence="inferred",
        notes="Endpoint inherited from upstream and may be wrong; tracked in issue tracker.",
    ),
    ModelSpec(
        id="soul-v2",
        label="Soul v2",
        kind="image",
        backend="web",
        endpoint="/jobs/v2/text2image_soul_v2",
        supports=("prompt", "aspect_ratio", "batch_size", "enhance_prompt", "seed", "quality"),
        constraints=("quality: 720p | 1080p | 2k",),
    ),
    ModelSpec(
        id="openai-hazel",
        label="OpenAI Hazel",
        kind="image",
        backend="web",
        endpoint="/jobs/openai-hazel",
        supports=("prompt", "aspect_ratio", "batch_size", "quality"),
        constraints=("quality: low | medium | high | 4k",),
    ),
    ModelSpec(
        id="flux_2",
        label="FLUX.2",
        kind="image",
        backend="web",
        endpoint="/jobs/flux-2",
        supports=("prompt", "aspect_ratio", "resolution", "seed"),
        constraints=("resolution: 1k | 2k", "model: pro | flex | max"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="z_image",
        label="Z-Image",
        kind="image",
        backend="web",
        endpoint="/jobs/z-image",
        supports=("prompt", "aspect_ratio"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="recraft_v4_1",
        label="Recraft v4.1",
        kind="image",
        backend="web",
        endpoint="/jobs/v2/recraft_v4_1",
        supports=("prompt", "aspect_ratio", "resolution"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="soul_cinematic",
        label="Soul Cinematic",
        kind="image",
        backend="web",
        endpoint="/jobs/v2/soul_cinematic",
        supports=("prompt", "aspect_ratio", "input_image_urls"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="soul_location",
        label="Soul Location",
        kind="image",
        backend="web",
        endpoint="/jobs/v2/soul_location",
        supports=("prompt", "aspect_ratio"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="grok_image",
        label="Grok Image",
        kind="image",
        backend="web",
        endpoint="/jobs/v2/grok_image",
        supports=("prompt", "aspect_ratio", "input_image_urls"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="kling_omni_image",
        label="Kling O1 Image",
        kind="image",
        backend="web",
        endpoint="/jobs/v2/kling_omni_image",
        supports=("prompt", "aspect_ratio", "resolution", "input_image_urls"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="cinematic_studio_2_5",
        label="Cinematic Studio 2.5",
        kind="image",
        backend="web",
        endpoint="/jobs/v2/cinematic_studio_2_5",
        supports=("prompt", "aspect_ratio", "resolution"),
        constraints=("resolution: 1k | 2k | 4k",),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
)

_WEB_VIDEO: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="kling3",
        label="Kling 3.0",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/kling3_0",
        supports=("prompt", "image_url", "end_image_url", "resolution", "sound", "seed"),
        constraints=("resolution: 720p | 1080p", "supports start/end frames + sound"),
    ),
    ModelSpec(
        id="kling-o3-flf",
        label="Kling 3.0 Omni FLF",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/kling_o3_flf",
        supports=("prompt", "image_url", "end_image_url", "resolution", "seed"),
    ),
    ModelSpec(
        id="kling2-6",
        label="Kling 2.6",
        kind="video",
        backend="web",
        endpoint="/jobs/kling2-6",
        supports=("prompt", "image_url", "duration", "seed"),
    ),
    ModelSpec(
        id="kling2-5-turbo",
        label="Kling 2.5 Turbo",
        kind="video",
        backend="web",
        # Shared endpoint with `kling`; model variant selected via request body.
        endpoint="/jobs/kling",
        supports=("prompt", "image_url", "duration", "seed"),
    ),
    ModelSpec(
        id="kling",
        label="Kling 2.1",
        kind="video",
        backend="web",
        endpoint="/jobs/kling",
        supports=("prompt", "image_url", "duration", "seed"),
    ),
    ModelSpec(
        id="grok",
        label="Grok Video",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/grok_video",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="wan2-6",
        label="Wan 2.6",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/wan2_6",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="wan2-5-video",
        label="Wan 2.5",
        kind="video",
        backend="web",
        endpoint="/jobs/wan2-5-video",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="seedance1-5",
        label="Seedance 1.5",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/seedance1_5",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="seedance",
        label="Seedance Pro",
        kind="video",
        backend="web",
        endpoint="/jobs/seedance",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="seedance2",
        label="Seedance 2.0",
        kind="video",
        backend="web",
        # Shared endpoint with seedance2-fast; variant selected via body.
        endpoint="/jobs/v2/seedance_2_0",
        supports=("prompt", "image_url", "duration", "resolution"),
    ),
    ModelSpec(
        id="seedance2-fast",
        label="Seedance 2.0 Fast",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/seedance_2_0",
        supports=("prompt", "image_url", "duration", "resolution"),
    ),
    ModelSpec(
        id="veo3",
        label="Veo 3",
        kind="video",
        backend="web",
        endpoint="/jobs/veo3",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="sora2-video",
        label="Sora 2",
        kind="video",
        backend="web",
        endpoint="/jobs/sora2-video",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="image2video",
        label="Image2Video (generic)",
        kind="video",
        backend="web",
        endpoint="/jobs/image2video",
        supports=("prompt", "image_url", "duration"),
    ),
    ModelSpec(
        id="veo3_1",
        label="Veo 3.1",
        kind="video",
        backend="web",
        endpoint="/jobs/veo3_1",
        supports=("prompt", "image_url", "aspect_ratio", "duration"),
        constraints=("duration: 4 | 6 | 8", "aspect_ratio: 16:9 | 9:16"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="veo3_1_lite",
        label="Veo 3.1 Lite",
        kind="video",
        backend="web",
        endpoint="/jobs/veo3_1_lite",
        supports=("prompt", "aspect_ratio", "duration"),
        constraints=("duration: 4 | 6 | 8",),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="wan2_7",
        label="Wan 2.7",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/wan2_7",
        supports=("prompt", "image_url", "duration", "resolution"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="kling3_0_turbo",
        label="Kling 3.0 Turbo",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/kling3_0_turbo",
        supports=("prompt", "image_url", "duration", "resolution"),
        constraints=("duration: 3-15", "resolution: 720p | 1080p"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="minimax_hailuo",
        label="MiniMax Hailuo 02",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/minimax_hailuo",
        supports=("prompt", "duration", "resolution"),
        constraints=("duration: 6 | 10", "resolution: 512 | 768 | 1080"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="grok_video_v15",
        label="Grok Video 1.5",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/grok_video_v15",
        supports=("prompt", "image_url", "duration", "resolution"),
        constraints=("duration: 2-15", "resolution: 480p | 720p"),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
    ModelSpec(
        id="cinematic_studio_3_0",
        label="Cinematic Studio 3.0",
        kind="video",
        backend="web",
        endpoint="/jobs/v2/cinematic_studio_3_0",
        supports=("prompt", "aspect_ratio", "duration"),
        constraints=("duration: 4-15",),
        confidence="inferred",
        notes="endpoint unverified — confirm with live auth",
    ),
)


@dataclass(frozen=True)
class Registry:
    by_id: dict[str, ModelSpec] = field(default_factory=dict)

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self.by_id[model_id]
        except KeyError as exc:
            raise UnknownModelError(model_id) from exc

    def list(
        self,
        kind: Kind | None = None,
        backend: Backend | None = None,
        include_unverified: bool = False,
    ) -> list[ModelSpec]:
        out = []
        for spec in self.by_id.values():
            if kind and spec.kind != kind:
                continue
            if backend and spec.backend != backend:
                continue
            if spec.confidence == "inferred" and not include_unverified:
                continue
            out.append(spec)
        return out


class UnknownModelError(KeyError):
    """Raised when a model_id is not in the registry."""


def _build_registry() -> Registry:
    by_id: dict[str, ModelSpec] = {}
    for spec in (*_OFFICIAL, *_WEB_IMAGE, *_WEB_VIDEO):
        if spec.id in by_id:
            raise RuntimeError(f"Duplicate model_id in registry: {spec.id}")
        by_id[spec.id] = spec
    return Registry(by_id=by_id)


REGISTRY: Registry = _build_registry()
"""The single global registry instance. Import this everywhere; do not mutate."""
