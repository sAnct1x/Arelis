"""User-browser control: attach/launch + drive (no credential entry)."""

from __future__ import annotations

from arelis.browser.aliases import resolve_target
from arelis.browser.session import BrowserSession, playwright_available

__all__ = [
    "BrowserSession",
    "playwright_available",
    "resolve_target",
]
