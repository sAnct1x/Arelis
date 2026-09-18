"""Export a session transcript to markdown.

The glass offers this next to per-reply copy. Tests drive the same helper
with a list of role/text dicts — no Qt, no model-facing tool.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from arelis.tools.safety import redact_secrets

_HEADING = "Conversation"
_ROLE_LABELS = {
    "user": "You",
    "assistant": "Arelis",
    "notice": "Notice",
    "system": "Notice",
}
_SKIP_ROLES = frozenset({"tool", "function"})
_KEEP_ROLES = frozenset(_ROLE_LABELS)
_UNSAFE_FILE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WINDOWS_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)


class EmptyTranscriptError(ValueError):
    """Nothing exportable — empty session, or only skipped tool JSON."""


# Older name — keep so existing callers do not break if they imported it.
EmptyTranscript = EmptyTranscriptError


def default_export_filename(title: str = "") -> str:
    """A safe ``*.md`` name from a session title."""
    raw = (title or "").strip() or "conversation"
    cleaned = _UNSAFE_FILE.sub("", raw)
    cleaned = re.sub(r"\s+", "-", cleaned).strip(" .-_")
    if not cleaned or cleaned.lower() in _WINDOWS_RESERVED:
        cleaned = "conversation"
    return f"{cleaned[:60]}.md"


def _message_text(message: Mapping[str, Any]) -> str:
    """Accept both store rows (``content``) and the test shape (``text``)."""
    return str(message.get("content") or message.get("text") or "")


def _looks_like_json(text: str) -> bool:
    stripped = (text or "").strip()
    if len(stripped) < 2 or stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
    except (ValueError, TypeError):
        return False
    return True


def _has_cleaned_notice(messages: Sequence[Mapping[str, Any]]) -> bool:
    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        if role in {"notice", "system"} and _message_text(message).strip():
            return True
    return False


def _export_blocks(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    """Role headings plus redacted bodies. Tool JSON is dropped when a notice exists."""
    has_notice = _has_cleaned_notice(messages)
    blocks: list[str] = []
    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        body = _message_text(message)
        if not body.strip():
            continue
        if role in _SKIP_ROLES:
            continue
        if has_notice and role not in _KEEP_ROLES and _looks_like_json(body):
            continue
        if role not in _KEEP_ROLES and _looks_like_json(body):
            continue
        label = _ROLE_LABELS.get(role) or (role.title() or "Other")
        cleaned = redact_secrets(body).rstrip()
        if not cleaned:
            continue
        blocks.append(f"## {label}\n\n{cleaned}\n")
    return blocks


def render_transcript(messages: Sequence[Mapping[str, Any]]) -> str:
    """Markdown for the session. Raises ``EmptyTranscriptError`` when nothing to write."""
    blocks = _export_blocks(messages)
    if not blocks:
        raise EmptyTranscriptError("Nothing to export — this conversation is empty.")
    return f"# {_HEADING}\n\n" + "\n".join(blocks)


def export_transcript(messages: Sequence[Mapping[str, Any]], dest: Path) -> Path:
    """Write the session as markdown at ``dest``. Returns the path written.

    Empty sessions fail before a file is created, so a titles-only stub cannot
    land on disk and look like a successful export.
    """
    dest = Path(dest)
    markdown = render_transcript(messages)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(markdown, encoding="utf-8", newline="\n")
    return dest
