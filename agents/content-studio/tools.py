"""Content Studio MCP tools."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def linkedin_post(ctx, topic: str, angle: str = "", source: str = "") -> dict:
    """Draft a LinkedIn post on a topic from recent call and deal themes plus approved proof points, checked by the
    Copy QA Gate. Saved as a draft; nothing is posted."""
    return _eng(ctx).linkedin_post(ctx, topic, angle, source)


def publish_post(ctx, draft_id: int, channel: str = "linkedin") -> dict:
    """Queue a passing post draft for publishing. A human must approve it first."""
    return _eng(ctx).publish_post(ctx, draft_id, channel)


def video_script(ctx, topic: str, seconds: float = 45) -> dict:
    """Short video script: a hook under 3 seconds, 2 to 4 beats and a call to action, timed to the word budget
    (seconds x words per second)."""
    return _eng(ctx).video_script(ctx, topic, seconds)


def captions(ctx, script_or_draft_id: str, seconds: float = 0) -> dict:
    """SRT captions from a script or a video_script draft id: lines up to 32 characters, 2 lines per cue,
    timing by word count."""
    return _eng(ctx).captions(ctx, script_or_draft_id, seconds or None)


def frame_qa(ctx, frames: list, width: int = 1080, height: int = 1920, duration: float = 0) -> dict:
    """Check on-screen text frames ({t, text, x, y, w, h}, optional end): safe zone, line length, reading time,
    banned words and dashes. Returns pass or fail with every issue."""
    return _eng(ctx).frame_qa(ctx, frames, width, height, duration or None)


TOOLS = {f.__name__: f for f in [linkedin_post, publish_post, video_script, captions, frame_qa]}
