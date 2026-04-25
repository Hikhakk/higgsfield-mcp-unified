"""FastMCP entrypoint."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from higgsfield_mcp import __version__
from higgsfield_mcp.models import Backend, Kind
from higgsfield_mcp.tools import (
    BackendPool,
    cancel_job,
    generate_image,
    generate_video,
    get_status,
    list_models,
    subscribe,
    upload_image,
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

    @mcp.tool
    async def list_models_tool(
        kind: Kind | None = None,
        backend: Backend | None = None,
        include_unverified: bool = False,
    ) -> dict[str, Any]:
        """List every supported Higgsfield model.

        Args:
            kind: Filter by 'image', 'video', or 'speech'.
            backend: Filter by 'official' or 'web'.
            include_unverified: Include models whose endpoint is suspected
                wrong upstream (currently: nano-banana-1).
        """
        return await list_models(kind=kind, backend=backend, include_unverified=include_unverified)

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
    ) -> dict[str, Any]:
        """Submit an image-generation request. Returns a job_handle to poll."""
        return await generate_image(
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
    ) -> dict[str, Any]:
        """Submit a video-generation request. Returns a job_handle to poll."""
        return await generate_video(
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

    @mcp.tool
    async def get_status_tool(job_handle: str) -> dict[str, Any]:
        """Check job state and return output URLs when ready."""
        return await get_status(pool, job_handle=job_handle)

    @mcp.tool
    async def cancel_job_tool(job_handle: str) -> dict[str, Any]:
        """Cancel a queued or in-progress job."""
        return await cancel_job(pool, job_handle=job_handle)

    @mcp.tool
    async def upload_image_tool(
        path: str | None = None,
        data_base64: str | None = None,
        mime: str = "image/png",
        backend: Backend = "web",
    ) -> dict[str, Any]:
        """Upload a local image and get a hosted URL to use as image_url."""
        return await upload_image(
            pool, path=path, data_base64=data_base64, mime=mime, backend=backend
        )

    @mcp.tool
    async def subscribe_tool(
        job_handle: str,
        poll_interval: float = 2.0,
        timeout_seconds: float = 600.0,
    ) -> dict[str, Any]:
        """Long-poll until the job reaches a terminal state (completed/failed/etc)."""
        return await subscribe(
            pool,
            job_handle=job_handle,
            poll_interval=poll_interval,
            timeout_seconds=timeout_seconds,
        )

    return mcp


def main() -> None:
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
