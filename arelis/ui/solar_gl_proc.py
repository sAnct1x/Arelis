"""Lifetime of the solar GPU context.

The dev shortcut starts this process as ``pythonw -m arelis --solar-gl``
(``scripts/install_desktop_shortcut.ps1``). ``arelis/main.py`` turns that flag
into ``ARELIS_SOLAR_GL``. No other code spawns that command. The GPU cost is
the offscreen context the solar page builds when it is actually shown
(``SolarPanel._ensure_space``).

Start that work only from a shown view. Stop it when the view closes or
hides, when a tool result arrives and the view is not on screen, after the
view has stayed hidden for ``ui.solar_gl_idle_s``, and on app exit.
"""

from __future__ import annotations

import subprocess
import time
from typing import Any

import yaml

_STOP_TIMEOUT_S = 1.0
_DEFAULT_IDLE_S = 60.0
_IDLE_POLL_MS = 5000

_proc: Any = None
_hidden_at: float | None = None
_idle_s: float | None = None
_panel: Any = None


def should_run() -> bool:
    """True when this process is allowed to use the solar GPU."""
    from arelis.ui.solar_gl import gl_wanted

    return gl_wanted()


def spawn_solar_gl() -> Any:
    """Child handle for the solar GPU, or None when GL stays in this process.

    Tests replace this with a fake child. Production does not launch a second
    ``pythonw -m arelis --solar-gl``: that command is this process.
    """
    return None


def reset_for_tests() -> None:
    """Drop the owned child and panel. Tests only."""
    global _proc, _hidden_at, _idle_s, _panel
    _proc = None
    _hidden_at = None
    _idle_s = None
    _panel = None


def idle_s() -> float:
    """Seconds a hidden solar view may keep the GPU. ``ui.solar_gl_idle_s``."""
    global _idle_s
    if _idle_s is not None:
        return _idle_s
    value = _DEFAULT_IDLE_S
    try:
        from arelis.config import load_config

        raw = (load_config().get("ui") or {}).get("solar_gl_idle_s", _DEFAULT_IDLE_S)
        parsed = float(raw)
        if parsed > 0:
            value = parsed
    except (OSError, TypeError, ValueError, ImportError, yaml.YAMLError):
        value = _DEFAULT_IDLE_S
    _idle_s = value
    return value


def on_solar_view_shown(panel: Any) -> None:
    """The solar page is on screen. Start the child if this process wants GL."""
    global _hidden_at
    _hidden_at = None
    _remember(panel)
    _ensure_idle_timer(panel)
    if not should_run():
        return
    _start_child()


def on_solar_view_hidden(panel: Any) -> None:
    """View closed or hidden. Stop the child and drop the offscreen context."""
    global _hidden_at
    if _hidden_at is None:
        _hidden_at = time.monotonic()
    _stop_child()
    _release_context(panel)


def poll_solar_gl_idle(panel: Any) -> None:
    """Stop the GPU after the view has been off screen for the idle budget."""
    global _hidden_at
    if _view_visible(panel) or getattr(panel, "_globe_mounting", False):
        _hidden_at = None
        return
    now = time.monotonic()
    if _hidden_at is None:
        _hidden_at = now
        return
    if now - _hidden_at < idle_s():
        return
    if _proc is None and getattr(panel, "_gl", None) is None:
        return
    on_solar_view_hidden(panel)


def release_solar_gl_after_tool(window: Any) -> None:
    """A tool finished. Keep the GPU only while the solar view is still up."""
    plate = getattr(window, "world_window", None)
    solar = getattr(plate, "solar", None) if plate is not None else None
    if solar is not None and _solar_page_visible(plate, solar):
        return
    shutdown_solar_gl()


def shutdown_solar_gl() -> None:
    """App exit, or a tool result with nothing on screen."""
    global _hidden_at
    _stop_child()
    _hidden_at = None
    panel = _bound_panel()
    if panel is not None:
        _release_context(panel)


def _start_child() -> None:
    global _proc
    if _running():
        return
    _reap_dead()
    child = spawn_solar_gl()
    if child is not None:
        _proc = child


def _stop_child() -> None:
    global _proc
    proc = _proc
    _proc = None
    if proc is None:
        return
    _terminate_then_kill(proc)


def _running() -> bool:
    proc = _proc
    if proc is None:
        return False
    try:
        return proc.poll() is None
    except OSError:
        return False


def _reap_dead() -> None:
    global _proc
    proc = _proc
    if proc is None:
        return
    try:
        alive = proc.poll() is None
    except OSError:
        _proc = None
        return
    if alive:
        return
    _reap(proc)
    _proc = None


def _terminate_then_kill(proc: Any) -> None:
    try:
        if proc.poll() is not None:
            _reap(proc)
            return
    except OSError:
        return
    try:
        proc.terminate()
    except OSError:
        pass
    if _wait(proc):
        return
    try:
        proc.kill()
    except OSError:
        pass
    _wait(proc)


def _wait(proc: Any) -> bool:
    try:
        proc.wait(timeout=_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False
    return True


def _reap(proc: Any) -> None:
    try:
        proc.wait(timeout=0)
    except (subprocess.TimeoutExpired, OSError):
        return


def _release_context(panel: Any) -> None:
    gl = getattr(panel, "_gl", None)
    if gl is None:
        return
    try:
        panel._gl = None
    except RuntimeError:
        return
    park = getattr(gl, "park", None)
    if callable(park):
        park()


def _remember(panel: Any) -> None:
    global _panel
    _panel = panel


def _bound_panel() -> Any:
    global _panel
    panel = _panel
    if panel is None:
        return None
    try:
        panel.isVisible()
    except RuntimeError:
        _panel = None
        return None
    return panel


def _view_visible(panel: Any) -> bool:
    try:
        if not panel.isVisible():
            return False
        win = panel.window()
    except RuntimeError:
        return False
    if win is not None and win is not panel:
        try:
            if win.isHidden():
                return False
        except RuntimeError:
            return False
    return True


def _solar_page_visible(plate: Any, solar: Any) -> bool:
    try:
        if plate.isHidden() or not solar.isVisible():
            return False
        active = getattr(plate, "solar_active", None)
        if callable(active):
            return bool(active())
    except RuntimeError:
        return False
    return True


def _ensure_idle_timer(panel: Any) -> None:
    if getattr(panel, "_solar_gl_idle", None) is not None:
        return
    from PySide6.QtCore import QTimer

    timer = QTimer(panel)
    timer.setInterval(_IDLE_POLL_MS)
    timer.timeout.connect(lambda panel=panel: poll_solar_gl_idle(panel))
    timer.start()
    panel._solar_gl_idle = timer
