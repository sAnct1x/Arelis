"""Download / upload / tab-PDF path jail. Roots and outputs/ only."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from arelis.paths import outputs_dir

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_FAKE_PDF = b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def downloads_dir() -> Path:
    path = outputs_dir() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def documents_dir() -> Path:
    path = outputs_dir() / "documents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str, *, fallback: str, suffix: str = "") -> str:
    raw = _SAFE_NAME.sub("_", str(name or "").strip())[:80].strip("._")
    leaf = raw or fallback
    extra = str(suffix or "")
    if extra and not leaf.lower().endswith(extra.lower()):
        leaf = f"{leaf}{extra}"
    return leaf


def under_outputs(path: Path) -> bool:
    try:
        path.resolve().relative_to(outputs_dir().resolve())
        return True
    except (OSError, ValueError):
        return False


def resolve_upload_path(
    raw: str,
    *,
    workspace: Any | None = None,
) -> tuple[Path | None, str]:
    """Allow workspace roots and outputs/ only. No home-drive scrape."""
    text = str(raw or "").strip()
    if not text:
        return None, "upload needs path (a file under workspace roots or outputs/)."
    try:
        resolved = Path(text).expanduser().resolve()
    except OSError:
        return None, f"Bad upload path: {text}"
    if not resolved.is_file():
        return None, f"Not a file: {resolved}"
    if under_outputs(resolved):
        return resolved, ""
    if workspace is not None:
        try:
            hit = workspace.resolve_read(str(resolved))
        except Exception as exc:
            return None, (
                f"Upload stays under workspace roots or outputs/: {exc}"
            )
        path = getattr(hit, "path", None)
        if path is None:
            return None, "Upload stays under workspace roots or outputs/."
        return Path(path), ""
    return None, (
        "Upload stays under workspace roots or outputs/. "
        "Add the folder in Settings → roots."
    )


def file_ready_payload(
    path: Path,
    *,
    kind: str,
    title: str = "",
) -> dict[str, Any]:
    abs_path = str(path.resolve())
    return {
        "file_ready": True,
        "path": abs_path,
        "abs_path": abs_path,
        "title": title or path.name,
        "kind": kind,
        "source": "browser",
        "show_card": True,
        "open": False,
        "format": path.suffix.lstrip(".").lower(),
    }


def fake_pdf_bytes() -> bytes:
    return _FAKE_PDF
