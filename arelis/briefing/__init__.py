"""Deterministic daily briefing — not a free-form model prompt."""

from arelis.briefing.builder import (
    BRIEFING_PROMPT,
    build_briefing,
    is_briefing_job,
)

__all__ = ["BRIEFING_PROMPT", "build_briefing", "is_briefing_job"]
