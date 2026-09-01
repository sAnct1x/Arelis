"""Open a local file in the OS default app, or show it in the folder."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_local_file(path: str | Path) -> None:
    """Open with whatever Windows (or the OS) already uses for that type."""
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(str(target))
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
        return
    subprocess.Popen(["xdg-open", str(target)])


def open_local_file_as(path: str | Path) -> None:
    """Show the OS Open with… picker when the platform has one."""
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(str(target))
    if sys.platform == "win32":
        os.startfile(str(target), "openas")  # type: ignore[attr-defined]
        return
    open_local_file(target)


def reveal_local_file(path: str | Path) -> None:
    """Show the file selected in Explorer / Finder / the file manager."""
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(str(target))
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{target}"])
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
        return
    subprocess.Popen(["xdg-open", str(target.parent)])
