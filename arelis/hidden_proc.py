"""Run subprocesses without flashing a console on Windows.

The glass UI is already windowless (`pythonw`). Child processes are not:
subprocess.run on Windows allocates a console unless CREATE_NO_WINDOW is set.
Patching subprocess.run here covers Tesseract, git, PowerShell probes, and
schtasks at launch — so we do not chase one call site at a time.

Do not subclass or replace subprocess.Popen. A Popen subclass plus STARTUPINFO
took the whole pythonw process down on the first child (Task Scheduler query
during UI start) with no traceback. Direct Popen callers (browser, Comfy) keep
their own flags. Individual helpers remain for tests and for code that runs
before install_hidden_subprocess().
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

_installed = False
_orig_run = subprocess.run


def hidden_kwargs() -> dict[str, Any]:
    """CREATE_NO_WINDOW so Windows does not allocate a console.

    STARTUPINFO / SW_HIDE is deliberately omitted. Combined with
    CREATE_NO_WINDOW it has returned ERROR_INVALID_PARAMETER (WinError 87)
    on some Windows/Python pairs, which pythonw then swallows.
    """
    if os.name != "nt":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not flags:
        return {}
    return {"creationflags": flags}


def _merge_hidden(kwargs: dict[str, Any]) -> dict[str, Any]:
    extra = hidden_kwargs()
    if not extra:
        return kwargs
    out = dict(kwargs)
    flags = int(extra.get("creationflags") or 0)
    out["creationflags"] = int(out.get("creationflags") or 0) | flags
    return out


def hidden_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """subprocess.run with a hidden console on Windows."""
    merged = _merge_hidden(kwargs)
    return _orig_run(args, **merged)


def install_hidden_subprocess() -> None:
    """Hide consoles for every subprocess.run in this process.

    Call once at program start (main). Leaves Popen untouched — replacing that
    class crashed launch. Set ARELIS_SHOW_CONSOLES=1 to leave children visible.
    """
    global _installed
    if _installed or os.name != "nt":
        return
    if os.environ.get("ARELIS_SHOW_CONSOLES", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return

    def _run(*args: Any, **kwargs: Any) -> Any:
        return _orig_run(*args, **_merge_hidden(kwargs))

    subprocess.run = _run  # type: ignore[assignment]
    _installed = True
