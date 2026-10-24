"""Verify that every external host in the Sentinel codebase is explicitly pinned.

Modeled directly after Arelis's tests/test_egress.py:
- Zero unapproved external hosts in Python source.
- Zero external CDN scripts/stylesheets in the 3D Overseer HTML/JS/CSS (100% local-first).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from sentinel.safety.network import ALLOWED_EGRESS_HOSTS

REPO_ROOT = Path(__file__).resolve().parents[1]
SENTINEL_PKG = REPO_ROOT / "sentinel"

LOOPBACK = frozenset({"127.0.0.1", "localhost", "0.0.0.0", "::1"})

ALLOWED_SOURCE_HOSTS: dict[str, str] = {
    **ALLOWED_EGRESS_HOSTS,
    "github.com": "Project source repository metadata URL in __source_url__",
    "www.w3.org": "Atom XML namespace URI (never fetched)",
}

_URL_RE = re.compile(r"https?://[^\s\"'<>`)}\]]+")


def test_all_source_urls_are_pinned_and_no_external_cdns() -> None:
    unapproved: list[tuple[str, str]] = []

    for path in SENTINEL_PKG.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".html", ".js", ".css", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _URL_RE.finditer(text):
            raw_url = match.group(0).rstrip(".,;:")
            if "{" in raw_url:
                raw_url = raw_url.split("{", 1)[0]
            parsed = urlparse(raw_url)
            host = (parsed.hostname or "").lower()
            if not host or host in LOOPBACK:
                continue
            if host not in ALLOWED_SOURCE_HOSTS:
                rel = str(path.relative_to(REPO_ROOT))
                unapproved.append((rel, host))

    assert not unapproved, f"Unapproved external hosts found in codebase: {unapproved}"
