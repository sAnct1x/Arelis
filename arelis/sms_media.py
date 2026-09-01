"""Inbound SMS links and pictures. No Qt — the tile renders what this returns."""

from __future__ import annotations

import html
import logging
import re
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from arelis.paths import state_dir
from arelis.tools.safety import is_blocked_url

log = logging.getLogger(__name__)

MAX_MEDIA_BYTES = 1_000_000
FINGERPRINT_WINDOW_S = 45.0
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".jfif"}
_PHOTO_BODIES = frozenset(
    {
        "photo",
        "image",
        "picture",
        "(photo)",
        "(image)",
        "sent a photo",
        "sent you a photo",
        "sent an image",
    }
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_recent_fps: deque[tuple[str, float]] = deque(maxlen=200)


def media_dir() -> Path:
    path = state_dir() / "sms_media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def looks_like_photo_body(body: str) -> bool:
    """True when the phone sent a picture label and no real caption."""
    text = (body or "").strip().casefold()
    if not text:
        return True
    if text in _PHOTO_BODIES:
        return True
    return text.startswith("photo") and len(text) < 24


def allowed_open_url(url: str) -> bool:
    """http(s) only. file:// and javascript: never become an anchor."""
    raw = (url or "").strip()
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    return True


def looks_like_image_url(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    return Path(path).suffix in IMAGE_SUFFIXES


def iter_http_urls(text: str) -> list[str]:
    found: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;:)")
        if url not in found:
            found.append(url)
    return found


def sms_body_html(text: str) -> str:
    """Escape the body and wrap allowed http(s) URLs as anchors."""
    raw = text or ""
    parts: list[str] = []
    last = 0
    for match in _URL_RE.finditer(raw):
        parts.append(html.escape(raw[last : match.start()]))
        url = match.group(0).rstrip(".,;:)")
        trailing = match.group(0)[len(url) :]
        if allowed_open_url(url):
            href = html.escape(url, quote=True)
            parts.append(f'<a href="{href}">{href}</a>')
        else:
            parts.append(html.escape(url))
        parts.append(html.escape(trailing))
        last = match.end()
    parts.append(html.escape(raw[last:]))
    return "".join(parts).replace("\n", "<br/>")


def body_needs_rich_text(text: str) -> bool:
    return any(allowed_open_url(url) for url in iter_http_urls(text or ""))


def inbox_media_url(row: dict[str, Any]) -> str:
    """Best-effort SMSGate / inbox media URL. Empty when the row is text-only."""
    for key in ("mediaUrl", "media_url", "imageUrl", "image_url"):
        val = str(row.get(key) or "").strip()
        if val.startswith("http"):
            return val
    urls = row.get("mediaUrls") or row.get("media_urls") or row.get("images")
    if isinstance(urls, list):
        for item in urls:
            val = str(item or "").strip()
            if val.startswith("http"):
                return val
    for group_key in ("parts", "attachments", "media"):
        group = row.get(group_key)
        if not isinstance(group, list):
            continue
        for part in group:
            if not isinstance(part, dict):
                continue
            for key in ("url", "mediaUrl", "contentUri", "path"):
                val = str(part.get(key) or "").strip()
                if val.startswith("http"):
                    return val
    return ""


def inbound_fingerprint(*, sender: str, body: str, media: str = "") -> str:
    return "|".join(
        (
            (sender or "").strip().casefold(),
            (body or "").strip().casefold(),
            (media or "").strip().casefold(),
        )
    )


def already_published_recent(fingerprint: str, *, now: float | None = None) -> bool:
    """True when the same sender+body arrived a moment ago under a different id."""
    stamp = time.monotonic() if now is None else now
    while _recent_fps and stamp - _recent_fps[0][1] > FINGERPRINT_WINDOW_S:
        _recent_fps.popleft()
    return any(item == fingerprint for item, _seen in _recent_fps)


def remember_published(fingerprint: str, *, now: float | None = None) -> None:
    stamp = time.monotonic() if now is None else now
    _recent_fps.append((fingerprint, stamp))


def _looks_like_image_bytes(data: bytes) -> bool:
    if len(data) < 8:
        return False
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def save_image_bytes(
    data: bytes,
    *,
    message_id: str,
    dest_dir: Path | None = None,
) -> Path | None:
    if not data or len(data) > MAX_MEDIA_BYTES:
        return None
    if not _looks_like_image_bytes(data):
        return None
    folder = dest_dir if dest_dir is not None else media_dir()
    folder.mkdir(parents=True, exist_ok=True)
    suffix = ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        suffix = ".png"
    elif data[:6] in {b"GIF87a", b"GIF89a"}:
        suffix = ".gif"
    elif data[:4] == b"RIFF":
        suffix = ".webp"
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", (message_id or "img")[:80]) or "img"
    path = folder / f"{safe}{suffix}"
    path.write_bytes(data)
    return path


def save_image_b64(
    raw: str,
    *,
    message_id: str,
    dest_dir: Path | None = None,
) -> Path | None:
    import base64

    text = (raw or "").strip()
    if not text:
        return None
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        data = base64.b64decode(text, validate=False)
    except (ValueError, TypeError):
        return None
    return save_image_bytes(data, message_id=message_id, dest_dir=dest_dir)


def fetch_image_url(
    url: str,
    *,
    message_id: str,
    dest_dir: Path | None = None,
    allow_private: bool = False,
    client: Any | None = None,
) -> Path | None:
    """Download an image. Public https by default; SMSGate LAN may pass allow_private."""
    if not allowed_open_url(url):
        return None
    if not allow_private:
        blocked = is_blocked_url(url)
        if blocked:
            return None
        if not looks_like_image_url(url):
            return None
    import httpx

    close = False
    http = client
    if http is None:
        http = httpx.Client(timeout=5.0, follow_redirects=True)
        close = True
    try:
        response = http.get(url)
        if response.status_code >= 400:
            return None
        ctype = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        data = response.content or b""
        if len(data) > MAX_MEDIA_BYTES:
            return None
        if ctype and not ctype.startswith("image/") and not _looks_like_image_bytes(data):
            return None
        if not _looks_like_image_bytes(data):
            return None
        return save_image_bytes(data, message_id=message_id, dest_dir=dest_dir)
    except Exception:
        log.debug("sms image fetch failed", exc_info=True)
        return None
    finally:
        if close:
            http.close()
