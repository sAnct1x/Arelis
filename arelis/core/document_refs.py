"""Resolve the last written document for 'email that' / 'open that' / export."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from arelis.paths import outputs_dir

_DOC_SUFFIXES = frozenset({".pdf", ".docx", ".xlsx", ".csv", ".md", ".txt"})

_PATH_MENTION = re.compile(
    r"(?i)("
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+[/\\])?"
    r"(?:outputs[/\\]documents[/\\]|documents[/\\])"
    r"[^\s\"'<>|]+\.(?:pdf|docx|xlsx|csv|md|txt)"
    r"|"
    r"[A-Za-z]:[\\/][^\s\"'<>|]+\.(?:pdf|docx|xlsx|csv|md|txt)"
    r")"
)

_JUST_DOCUMENT = re.compile(
    r"(?i)\b("
    r"(?:just\s+)?(?:wrote|created|made|saved|exported)|"
    r"(?:this|that|the)\s+(?:file|document|pdf|docx|spreadsheet|csv|markdown|note)|"
    r"the\s+(?:file|document|pdf)\s+(?:you|we)\s+(?:just\s+)?"
    r"(?:wrote|created|made|saved|exported)"
    r")\b"
)

_REVISE = re.compile(
    r"(?i)\b("
    r"fix|update|revise|overwrite|replace|"
    r"make\s+it\s+longer|add\s+a\s+section|expand\s+(?:it|this|that)|"
    r"edit\s+(?:it|this|that)|change\s+(?:section|the\s+draft)"
    r")\b"
)

_ANOTHER = re.compile(
    r"(?i)\b("
    r"another|a\s+second|one\s+more|a\s+new\s+one|make\s+another"
    r")\b"
)

_EXPORT = re.compile(
    r"(?i)\b("
    r"export\s+(?:that|this|it)|"
    r"save\s+(?:that|this|it)\s+as|"
    r"(?:as|to)\s+(?:a\s+)?(?:pdf|docx|word|excel|xlsx|csv)"
    r")\b"
)

_OPEN_LAST = re.compile(
    r"(?i)^\s*(?:please\s+)?"
    r"(?:"
    r"(?:open|show)\s+(?:that|this|it)\b"
    r"(?:\s+(?:file|document|pdf|docx|spreadsheet|csv|markdown|note))?"
    r"|"
    r"(?:open|show)\s+the\s+(?:file|document|pdf|docx|spreadsheet|csv|markdown|note)\b"
    r"|"
    r"show\s+(?:that|this|it|the\s+file)\s+in\s+(?:explorer|folder|finder)"
    r")\s*[.!]?\s*$"
)

_FORMAT_WORD = re.compile(
    r"(?i)\b(pdf|docx|xlsx|csv|markdown|word|excel|spreadsheet|text\s+file)\b"
)


def mentions_recent_document(text: str) -> bool:
    """True when they point at the last written file without a path."""
    return bool(_JUST_DOCUMENT.search(text or ""))


def detect_document_revise(text: str) -> bool:
    raw = text or ""
    if detect_document_another(raw):
        return False
    return bool(_REVISE.search(raw) or _EXPORT.search(raw))


def detect_document_another(text: str) -> bool:
    return bool(_ANOTHER.search(text or ""))


def detect_document_export(text: str) -> bool:
    return bool(_EXPORT.search(text or ""))


def match_open_last_document(text: str) -> bool:
    """True for a whole-utterance 'open that' / 'open the file'."""
    return bool(_OPEN_LAST.match((text or "").strip()))


def format_from_text(text: str) -> str:
    """Named format in the ask, or empty."""
    match = _FORMAT_WORD.search(text or "")
    if not match:
        return ""
    word = match.group(1).lower()
    aliases = {
        "word": "docx",
        "excel": "xlsx",
        "spreadsheet": "xlsx",
        "markdown": "md",
        "text file": "txt",
    }
    return aliases.get(word, word)


def _history_pairs(history: list[Any] | None) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for item in history or []:
        if hasattr(item, "role"):
            note = str(getattr(item, "note", "") or "")
            out.append(
                (str(item.role), str(getattr(item, "content", "") or ""), note)
            )
        elif isinstance(item, dict):
            out.append(
                (
                    str(item.get("role") or ""),
                    str(item.get("content") or ""),
                    str(item.get("note") or ""),
                )
            )
    return out


def _usable_file(raw: str) -> str:
    text = (raw or "").strip().strip("\"'`")
    if not text:
        return ""
    path = Path(text)
    if not path.is_file():
        alt = outputs_dir() / "documents" / path.name
        if alt.is_file():
            path = alt
        else:
            return ""
    if path.suffix.lower() not in _DOC_SUFFIXES:
        return ""
    try:
        return str(path.resolve())
    except OSError:
        return ""


def latest_document_path(
    history: list[Any] | None = None,
    receipts: list[Any] | None = None,
) -> str:
    """Newest written document in this thread, or empty."""
    for rec in reversed(list(receipts or [])):
        if not isinstance(rec, dict):
            continue
        if str(rec.get("tool") or rec.get("action") or "") not in {
            "document",
        }:
            continue
        for key in ("abs_path", "path"):
            hit = _usable_file(str(rec.get(key) or ""))
            if hit:
                return hit
    blobs: list[str] = []
    for role, content, note in reversed(_history_pairs(history)):
        if role in {"assistant", "tool", "system"} or note:
            blobs.append(f"{content}\n{note}")
    for blob in blobs:
        for match in reversed(list(_PATH_MENTION.finditer(blob))):
            hit = _usable_file(match.group(1))
            if hit:
                return hit
    return ""


def fill_document_args(
    args: dict[str, Any],
    *,
    user_text: str = "",
    history: list[Any] | None = None,
    receipts: list[Any] | None = None,
    room_kind: str = "",
) -> dict[str, Any]:
    """Fill replace / filename / from_path / format from this turn."""
    out = dict(args)
    last = latest_document_path(history, receipts)
    last_path = Path(last) if last else None
    ask = user_text or ""
    another = detect_document_another(ask)
    revise = detect_document_revise(ask)
    export = detect_document_export(ask)

    if not str(out.get("format") or "").strip():
        named = format_from_text(ask)
        if named:
            out["format"] = named
        elif (room_kind or "").strip().lower() == "writing":
            out["format"] = "md"

    if another:
        out["replace"] = "false"
    elif revise or export:
        out["replace"] = "true"
        if last_path is not None and not str(out.get("filename") or "").strip():
            fmt = str(out.get("format") or last_path.suffix.lstrip(".")).strip()
            out["filename"] = f"{last_path.stem}.{fmt}" if fmt else last_path.name

    if (
        export
        and last_path is not None
        and last_path.suffix.lower() in {".md", ".txt", ".csv"}
        and not str(out.get("from_path") or "").strip()
        and not str(out.get("body") or "").strip()
    ):
        out["from_path"] = last
        if last_path.suffix.lower() == ".md" and not str(out.get("title") or "").strip():
            out["title"] = last_path.stem.replace("-", " ")

    if (
        (revise or mentions_recent_document(ask))
        and last_path is not None
        and not str(out.get("filename") or "").strip()
        and not another
    ):
        fmt = str(out.get("format") or last_path.suffix.lstrip(".")).strip()
        out["filename"] = f"{last_path.stem}.{fmt}" if fmt else last_path.name
        out.setdefault("replace", "true")
    return out


def fill_doc_extract_args(
    args: dict[str, Any],
    *,
    user_text: str = "",
    history: list[Any] | None = None,
    receipts: list[Any] | None = None,
) -> dict[str, Any]:
    """Fill a missing extract path from the last PDF in this thread."""
    out = dict(args)
    if str(out.get("path") or "").strip():
        return out
    if not mentions_recent_document(user_text or ""):
        return out
    last = latest_document_path(history, receipts)
    if last and Path(last).suffix.lower() == ".pdf":
        out["path"] = last
    return out
