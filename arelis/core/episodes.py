"""Format recent episodes for optional system-prompt injection.

Episodes are explicit typed memories (manual or confirmed). They are never
auto-written from every turn — callers choose when to pin them into context.
"""

from __future__ import annotations

from typing import Any, Protocol


class _EpisodeStore(Protocol):
    def list_episodes(
        self, *, limit: int = 20, project: str | None = None
    ) -> list[dict[str, Any]]: ...


def episodes_prompt_line(store: _EpisodeStore, limit: int = 3) -> str:
    """One short system block of recent episodes, or empty when none."""
    cap = max(1, min(int(limit), 12))
    rows = store.list_episodes(limit=cap)
    if not rows:
        return ""
    lines = [
        "Recent episodes (explicit summaries the user stored; not a full history):"
    ]
    for row in rows:
        summary = " ".join(str(row.get("summary") or "").split())
        if not summary:
            continue
        if len(summary) > 160:
            summary = summary[:159].rstrip() + "…"
        lines.append(f"- {summary}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
