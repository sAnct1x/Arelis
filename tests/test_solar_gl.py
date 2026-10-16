"""OpenGL solar viewport helpers. The widget itself stays off under offscreen."""

from __future__ import annotations

import os
import subprocess

import pytest

from arelis.ui.solar_gl import (
    framebuffer_size,
    make_sphere,
)


def test_main_solar_gl_flag_sets_env_before_version_exits(monkeypatch) -> None:
    """The desktop shortcut cannot set env vars. --solar-gl has to do that job."""
    monkeypatch.delenv("ARELIS_SOLAR_GL", raising=False)
    from arelis.main import main

    with pytest.raises(SystemExit):
        main(["--solar-gl", "--version"])
    assert os.environ.get("ARELIS_SOLAR_GL") == "1"


def test_make_sphere_indexed() -> None:
    verts, idx = make_sphere(8, 4)
    nvert = verts.size // 8
    assert nvert == 9 * 5
    assert idx.min() == 0
    assert int(idx.max()) < nvert
    assert idx.size % 3 == 0


def test_earth_gl_cache_ignores_spin_micro_moves() -> None:
    from arelis.ui.solar_gl import earth_gl_cache_key

    base = dict(
        width=800,
        height=600,
        look=(0.0, 0.0, 0.0),
        up=(0.0, 0.0, 1.0),
        paused=False,
        fov_y=50.0,
        inspect="Earth",
    )
    a = earth_gl_cache_key(eye=(1_000_000.0, 0.0, 0.0), t=1.2, **base)
    near = earth_gl_cache_key(eye=(1_000_040.0, 0.0, 0.0), t=1.2, **base)
    far = earth_gl_cache_key(eye=(1_000_200.0, 0.0, 0.0), t=1.2, **base)
    later = earth_gl_cache_key(eye=(1_000_000.0, 0.0, 0.0), t=1.8, **base)
    next_s = earth_gl_cache_key(eye=(1_000_000.0, 0.0, 0.0), t=2.1, **base)
    hour = earth_gl_cache_key(
        eye=(1_000_000.0, 0.0, 0.0), t=29.0, t_step=30.0, **base
    )
    hour_near = earth_gl_cache_key(
        eye=(1_000_000.0, 0.0, 0.0), t=1.2, t_step=30.0, **base
    )
    assert a == near
    assert a != far
    assert a == later
    assert a != next_s
    assert hour == hour_near


def test_framebuffer_size_caps_readback() -> None:
    from arelis.ui.solar_gl import _FB_CLOSE

    assert framebuffer_size(800, 600) == (800, 600)
    # A 1440p plate renders native: upscaling a 1920 readback is the blur.
    assert framebuffer_size(2560, 1440) == (2560, 1440)
    # Concrete bounds, not _FB_CAP: comparing the cap against itself would hold
    # for any number anyone typed there, including one that stalls on readback.
    w, h = framebuffer_size(3840, 2160)
    assert 2500 < max(w, h) <= 2560
    assert w / h == pytest.approx(3840 / 2160, rel=0.02)
    assert framebuffer_size(2160, 3840)[1] == max(w, h)
    assert max(framebuffer_size(3840, 2160, cap=1920)) <= 1920
    # Inspecting no longer asks for a bigger frame than the base cap.
    assert framebuffer_size(3840, 2160, cap=_FB_CLOSE) == (w, h)


class _GlChild:
    """Child that ignores terminate, then dies on kill. No real process."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.reaped = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("solar-gl", timeout or 0)
        self.reaped = True
        return self.returncode


class _Quiet:
    def append(self, *_args, **_kwargs) -> None:
        return None

    def set_turn_visible(self, *_args, **_kwargs) -> None:
        return None

    def set_drive(self, *_args, **_kwargs) -> None:
        return None


class _PlateHost:
    """Just enough window for a tool result to reach the real solar page."""

    def __init__(self, plate) -> None:
        self.world_window = plate
        self.thinking = _Quiet()
        self.conversation = _Quiet()
        self.persona_dock = None
        self.act_persona = None
        self._workspace_tool_args: dict = {}

    def _reveal_dock(self, *_args, **_kwargs) -> None:
        return None

    def _apply_tile(self, name: str, *, show: bool, page: str = "") -> None:
        from arelis.ui.world_host import show_world

        if (name or "").strip().lower() != "world":
            return
        if not show:
            self.world_window.hide()
            return
        show_world(
            self.world_window,
            self.world_window.frameGeometry(),
            page=page,
            placed=True,
        )


def test_closing_the_solar_view_reaps_its_gl_child(qt_app, monkeypatch) -> None:
    """A tool result must not open solar on its own. Closing the page reaps GL."""
    from arelis.core.events import Event, EventType
    from arelis.spatial.scene import WorldScene
    from arelis.ui import solar_gl_proc
    from arelis.ui.event_host import dispatch_event
    from arelis.ui.panels.solar import SolarPanel
    from arelis.ui.world_window import WorldWindow

    spawned: list[_GlChild] = []

    def _spawn() -> _GlChild:
        child = _GlChild()
        spawned.append(child)
        return child

    monkeypatch.setattr(solar_gl_proc, "should_run", lambda: True)
    monkeypatch.setattr(solar_gl_proc, "spawn_solar_gl", _spawn)
    monkeypatch.setattr(SolarPanel, "_ensure_ic", lambda self: None)
    solar_gl_proc.reset_for_tests()
    plate = WorldWindow(WorldScene())
    host = _PlateHost(plate)
    try:
        plate.show()
        qt_app.processEvents()
        assert plate.stack.currentWidget() is plate.chooser

        def _result(tool: str, data: dict) -> None:
            dispatch_event(
                host,
                Event(
                    EventType.TOOL_RESULT,
                    {"tool": tool, "ok": True, "output": "", "data": data},
                ),
            )
            qt_app.processEvents()

        # Call args have no page field. Result data naming solar must not build it.
        dispatch_event(
            host,
            Event(
                EventType.TOOL_START,
                {"tool": "tile", "args": {"action": "open", "name": "world"}},
            ),
        )
        _result("tile", {"open": True, "name": "world", "page": "solar"})
        _result("solar", {"action": "load"})
        _result("earth", {"action": "enter"})
        assert plate.stack.currentWidget() is plate.chooser
        assert plate.solar_active() is False
        assert spawned == []

        # The existing tile page field is an explicit ask, so the page may open.
        dispatch_event(
            host,
            Event(
                EventType.TOOL_START,
                {
                    "tool": "tile",
                    "args": {"action": "open", "name": "world", "page": "solar"},
                },
            ),
        )
        _result("tile", {"open": True, "name": "world", "page": "solar"})
        assert plate.solar_active()
        assert spawned
        child = spawned[-1]
        assert child.poll() is None
        # Already the visible page: a later solar or earth result stays there.
        _result("solar", {"action": "status"})
        _result("earth", {"action": "status"})
        assert plate.solar_active()
        assert child.poll() is None
        plate.close()
        qt_app.processEvents()
        assert child.poll() is not None
        assert child.reaped
    finally:
        solar_gl_proc.reset_for_tests()
        plate.deleteLater()
        qt_app.processEvents()


