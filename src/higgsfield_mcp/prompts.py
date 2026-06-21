"""MCP prompt templates for common Higgsfield generation intents.

These are reusable, parameterized prompt scaffolds a client can fetch and feed
into ``generate_image`` / ``generate_video``. Exposing prompts is something the
hosted MCP does not do for clients.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt
    def cinematic_shot(subject: str, mood: str = "dramatic", lens: str = "anamorphic") -> str:
        """A cinematic still/video prompt for a subject with a given mood and lens."""
        return (
            f"Cinematic shot of {subject}. {mood} lighting, {lens} lens, shallow depth of field, "
            "filmic color grade, volumetric light, 35mm grain, composed with the rule of thirds."
        )

    @mcp.prompt
    def product_360(product: str, surface: str = "matte studio backdrop") -> str:
        """A turntable product-showcase prompt."""
        return (
            f"Studio product showcase of {product} on a {surface}, slow 360-degree turntable, "
            "soft key light with rim highlight, crisp reflections, high detail, commercial photography."
        )

    @mcp.prompt
    def animate_portrait(subject: str, motion: str = "subtle head turn and natural blink") -> str:
        """An image-to-video prompt to gently animate a portrait."""
        return (
            f"Animate this portrait of {subject}: {motion}, breathing motion, soft ambient light shift, "
            "preserve identity and facial features, photoreal, smooth natural motion."
        )

    @mcp.prompt
    def action_sequence(subject: str, action: str, setting: str = "urban environment") -> str:
        """A dynamic action video prompt."""
        return (
            f"Dynamic action sequence: {subject} {action} in a {setting}. Fast camera movement, "
            "motion blur, dramatic angles, high energy, cinematic pacing, detailed environment."
        )

    @mcp.prompt
    def b_roll(scene: str, style: str = "documentary") -> str:
        """An atmospheric b-roll video prompt."""
        return (
            f"Atmospheric {style} b-roll of {scene}. Slow, steady camera movement, natural light, "
            "rich texture and depth, ambient mood, color-graded for {style} tone."
        )
