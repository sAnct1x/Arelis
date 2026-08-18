"""Windows subprocess flags that keep a console from flashing over the UI."""

from __future__ import annotations

import os
import subprocess

from arelis.hidden_proc import hidden_kwargs, install_hidden_subprocess


def test_hidden_kwargs_hide_console_on_windows() -> None:
    kwargs = hidden_kwargs()
    if os.name != "nt":
        assert kwargs == {}
        return
    flags = int(kwargs.get("creationflags") or 0)
    assert flags & getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # STARTUPINFO + CREATE_NO_WINDOW crashed launch on this machine.
    assert "startupinfo" not in kwargs


def test_install_hidden_subprocess_is_safe_to_call_twice() -> None:
    install_hidden_subprocess()
    install_hidden_subprocess()


def test_install_does_not_replace_popen() -> None:
    """Subclassing Popen took pythonw down on the first child at launch."""
    original = subprocess.Popen
    install_hidden_subprocess()
    assert subprocess.Popen is original
