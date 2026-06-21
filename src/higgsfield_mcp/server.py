"""FastMCP entrypoint."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from higgsfield_mcp import __version__
from higgsfield_mcp.models import Backend, Kind
from higgsfield_mcp.prompts import register_prompts
from higgsfield_mcp.resources import register_resources
from higgsfield_mcp.schemas import (
    Balance,
    BatchResult,
    CancelResult,
    Character,
    CharacterDeleted,
    CharacterList,
    JobList,
    JobStatusResult,
    ModelList,
    NameList,
    PreflightResult,
    RecommendResult,
    SubmitResult,
    UploadResult,
    ValidateResult,
)
from higgsfield_mcp.tools import (
    BackendPool,
    cancel_job,
    create_character,
    delete_character,
    generate_batch,
    generate_image,
    generate_speech_video,
    generate_video,
    get_balance,
    get_character,
    get_status,
    list_characters,
    list_jobs,
    list_models,
    list_motions,
    list_soul_styles,
    preflight_check,
    recommend_model,
    subscribe,
    upload_image,
    validate_params,
)


def build_server() -> FastMCP:
    mcp = FastMCP(
        name="higgsfield-mcp",
        instructions=(
            "Higgsfield AI image and video generation. Always call list_models() first "
            "to discover the right model_id; do not guess. The cloud.higgsfield.ai web "
            "backend is opt-in via HIGGSFIELD_ENABLE_WEB_BACKEND=1."
        ),
        version=__version__,
    )
    pool = BackendPool()
    register_resources(mcp)
    register_prompts(mcp)

    @mcp.tool
    async def list_models_tool(
        kind: Kind | None = None,
        backend: Backend | None = None,
        include_unverified: bool = False,
    ) -> ModelList:
        """List every supported Higgsfield model.

        Args:
            kind: Filter by 'image', 'video', or 'speech'.
            backend: Filter by 'official' or 'web'.
            include_unverified: Include models whose endpoint is suspected
                wrong upstream (currently: nano-banana-1).
        """
        return ModelList.model_validate(
            await list_models(kind=kind, backend=backend, include_unverified=include_unverified)
        )

    @mcp.tool
    async def generate_image_tool(
        model_id: str,
        prompt: str,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        quality: str | None = None,
        image_url: str | None = None,
        input_image_urls: list[str] | None = None,
        seed: int | None = None,
        batch_size: int | None = None,
        enhance_prompt: bool | None = None,
        soul_id: str | None = None,
        soul_strength: float | None = None,
    ) -> SubmitResult:
        """Submit an image-generation request. Returns a job_handle to poll."""
        return SubmitResult.model_validate(
            await generate_image(
                pool,
                model_id=model_id,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                quality=quality,
                image_url=image_url,
                input_image_urls=input_image_urls,
                seed=seed,
                batch_size=batch_size,
                enhance_prompt=enhance_prompt,
                soul_id=soul_id,
                soul_strength=soul_strength,
            )
        )

    @mcp.tool
    async def generate_video_tool(
        model_id: str,
        prompt: str,
        image_url: str | None = None,
        end_image_url: str | None = None,
        duration: int | None = None,
        resolution: str | None = None,
        sound: bool | None = None,
        seed: int | None = None,
    ) -> SubmitResult:
        """Submit a video-generation request. Returns a job_handle to poll."""
        return SubmitResult.model_validate(
            await generate_video(
                pool,
                model_id=model_id,
                prompt=prompt,
                image_url=image_url,
                end_image_url=end_image_url,
                duration=duration,
                resolution=resolution,
                sound=sound,
                seed=seed,
            )
        )

    @mcp.tool
    async def get_status_tool(job_handle: str) -> JobStatusResult:
        """Check job state and return output URLs when ready."""
        return JobStatusResult.model_validate(await get_status(pool, job_handle=job_handle))

    @mcp.tool
    async def cancel_job_tool(job_handle: str) -> CancelResult:
        """Cancel a queued or in-progress job."""
        return CancelResult.model_validate(await cancel_job(pool, job_handle=job_handle))

    @mcp.tool
    async def upload_image_tool(
        path: str | None = None,
        data_base64: str | None = None,
        mime: str = "image/png",
        backend: Backend = "web",
    ) -> UploadResult:
        """Upload a local image and get a hosted URL to use as image_url."""
        return UploadResult.model_validate(
            await upload_image(pool, path=path, data_base64=data_base64, mime=mime, backend=backend)
        )

    @mcp.tool
    async def subscribe_tool(
        job_handle: str,
        poll_interval: float = 2.0,
        timeout_seconds: float = 600.0,
    ) -> JobStatusResult:
        """Long-poll until the job reaches a terminal state (completed/failed/etc)."""
        return JobStatusResult.model_validate(
            await subscribe(
                pool,
                job_handle=job_handle,
                poll_interval=poll_interval,
                timeout_seconds=timeout_seconds,
            )
        )

    @mcp.tool
    async def preflight_check_tool() -> PreflightResult:
        """Check auth + config for both backends before submitting a generation."""
        return PreflightResult.model_validate(await preflight_check(pool))

    @mcp.tool
    async def recommend_model_tool(
        intent: str,
        kind: Kind | None = None,
        top: int = 5,
        include_unverified: bool = False,
    ) -> RecommendResult:
        """Suggest models for a described goal. Ranks by keyword overlap; verified-only by default."""
        return RecommendResult.model_validate(
            await recommend_model(
                intent=intent, kind=kind, top=top, include_unverified=include_unverified
            )
        )

    @mcp.tool
    async def validate_params_tool(model_id: str, params: dict[str, Any]) -> ValidateResult:
        """Pre-flight check params against a model's supported set (no generation)."""
        return ValidateResult.model_validate(await validate_params(model_id, params))

    @mcp.tool
    async def create_character_tool(name: str, image_urls: list[str]) -> Character:
        """Train a reusable Soul character from reference images. Results best-effort until verified."""
        return Character.model_validate(
            await create_character(pool, name=name, image_urls=image_urls)
        )

    @mcp.tool
    async def get_character_tool(character_id: str) -> Character:
        """Check a Soul character's training status."""
        return Character.model_validate(await get_character(pool, character_id=character_id))

    @mcp.tool
    async def list_characters_tool(page: int = 1, page_size: int = 50) -> CharacterList:
        """List trained Soul characters."""
        return CharacterList.model_validate(
            await list_characters(pool, page=page, page_size=page_size)
        )

    @mcp.tool
    async def delete_character_tool(character_id: str) -> CharacterDeleted:
        """Delete a trained Soul character."""
        return CharacterDeleted.model_validate(
            await delete_character(pool, character_id=character_id)
        )

    @mcp.tool
    async def get_balance_tool() -> Balance:
        """Get available credits + plan (best-effort; official API key required)."""
        return Balance.model_validate(await get_balance(pool))

    @mcp.tool
    async def list_jobs_tool(page: int = 1, page_size: int = 20) -> JobList:
        """List recent generations (history) from the official backend."""
        return JobList.model_validate(await list_jobs(pool, page=page, page_size=page_size))

    @mcp.tool
    async def list_soul_styles_tool() -> NameList:
        """List Soul image style presets to pick by name."""
        return NameList.model_validate(await list_soul_styles(pool))

    @mcp.tool
    async def list_motions_tool() -> NameList:
        """List DOP motion presets for image-to-video."""
        return NameList.model_validate(await list_motions(pool))

    @mcp.tool
    async def generate_speech_video_tool(
        image_url: str, audio_url: str, prompt: str | None = None
    ) -> SubmitResult:
        """Talking-head video from a face image + WAV audio (official backend)."""
        return SubmitResult.model_validate(
            await generate_speech_video(
                pool, image_url=image_url, audio_url=audio_url, prompt=prompt
            )
        )

    @mcp.tool
    async def generate_batch_tool(requests: list[dict[str, Any]]) -> BatchResult:
        """Submit multiple generations at once. Each request: {kind, model_id, prompt, ...params}."""
        return BatchResult.model_validate(await generate_batch(pool, requests))

    return mcp


def _maybe_warn_web_backend() -> None:
    """Print a stderr warning if the experimental web backend is enabled."""
    import os
    import sys

    if os.getenv("HIGGSFIELD_ENABLE_WEB_BACKEND") in ("1", "true", "True", "yes"):
        print(
            "[higgsfield-mcp] WARN: web backend is enabled. "
            "This is EXPERIMENTAL and reverse-engineered. "
            "Expect Cloudflare/Datadome blocks, ~1-min JWT churn, and silent schema "
            "drift. See the README 'Web backend is experimental' section. "
            "Official models via HIGGSFIELD_API_KEY are unaffected.",
            file=sys.stderr,
        )


def main() -> None:
    _maybe_warn_web_backend()
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
