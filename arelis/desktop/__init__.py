"""Drive the user's Windows session: launch, focus, type, snapshot, click."""

from __future__ import annotations

from arelis.desktop.aliases import resolve_app
from arelis.desktop.session import DesktopSession

__all__ = ["DesktopSession", "resolve_app"]
