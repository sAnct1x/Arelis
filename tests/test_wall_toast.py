"""Local tray toast after a browser wall wait. No network, no extra packages."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from arelis.core.events import Event, EventType

_UI = Path(__file__).resolve().parents[1] / "arelis" / "ui"
_FORBIDDEN = frozenset(
    {
        "winotify",
        "win10toast",
        "plyer",
        "windows-toasts",
        "requests",
        "httpx",
        "socket",
        "smtplib",
    }
)


class FakeTimer:
    """Single-shot stand-in. Tests fire it; nothing waits on a real clock."""

    def __init__(self, parent=None) -> None:
        self.parent = parent
        self._cb = None
        self.active = False
        self.interval_ms = 0
        self.timeout = self

    def setSingleShot(self, _value: bool) -> None:
        return None

    def connect(self, cb) -> None:
        self._cb = cb

    def start(self, ms: int = 0) -> None:
        self.interval_ms = int(ms)
        self.active = True

    def stop(self) -> None:
        self.active = False

    def fire(self) -> None:
        if not self.active or self._cb is None:
            return
        self.active = False
        self._cb()


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _window(*, delay_s: float = 0.05, tray=None):
    shown: list[str] = []

    def show_message(title, message, *_a, **_k):
        shown.append(str(message))

    if tray is None:
        tray = SimpleNamespace(showMessage=show_message)
    window = SimpleNamespace(
        config={"agent": {"wall_toast_after_s": delay_s}},
        _tray=tray,
        conversation=SimpleNamespace(
            set_drive_your_turn=lambda *_a, **_k: None,
            set_drive_paused=lambda *_a, **_k: None,
            set_drive_status=lambda *_a, **_k: None,
            dismiss_confirm=lambda: None,
            confirm=SimpleNamespace(_confirm_id=""),
        ),
        chat=SimpleNamespace(
            add_system=lambda *_a, **_k: None,
            show_progress=lambda *_a, **_k: None,
            finish_assistant=lambda *_a, **_k: None,
        ),
        thinking=SimpleNamespace(append=lambda *_a, **_k: None),
        _turn_busy=False,
        _ignore_cancel_echo=False,
        _force_quit=False,
        _disposed=False,
        _apply_stop_ui=lambda **_k: None,
        _later=lambda *_a, **_k: None,
        _show_next_pending_confirm=lambda: None,
        _mobile_foreign=False,
        _assistant_streaming=False,
        _set_busy=lambda *_a, **_k: None,
        _clear_model_loading=lambda: None,
        _set_confirm_pending=lambda *_a, **_k: None,
        store=None,
        shown=shown,
    )
    return window


def _arm_hooks(monkeypatch) -> None:
    from arelis.ui import event_host

    monkeypatch.setattr(event_host, "QTimer", FakeTimer, raising=False)
    monkeypatch.setattr(
        event_host, "_arelis_window_is_active", lambda: False, raising=False
    )


def _your_turn(*, kind: str = "captcha", url: str = "https://example.com/wall") -> Event:
    return Event(
        EventType.TOOL_RESULT,
        {
            "tool": "browser",
            "ok": True,
            "output": "Your turn. Captcha.",
            "data": {"code": "YOUR_TURN", "wall": kind, "url": url},
        },
    )


def test_wall_toasts_once_after_delay_not_before(monkeypatch) -> None:
    from arelis.ui.event_host import dispatch_event

    _arm_hooks(monkeypatch)
    window = _window()
    dispatch_event(window, _your_turn())
    assert window.shown == []
    timer = getattr(window, "_wall_toast_timer", None)
    assert timer is not None
    assert timer.active
    assert timer.interval_ms == 50
    timer.fire()
    assert len(window.shown) == 1
    body = window.shown[0]
    assert "Still waiting on you" in body
    assert "\u2014" not in body
    timer.fire()
    assert len(window.shown) == 1


_DAY_MS = 86_400_000
_DELAY_CASES = (
    (float("nan"), 0),
    (float("inf"), 0),
    (float("-inf"), 0),
    (-5, 0),
    (0, 0),
    ("abc", 0),
    ("", 0),
    (None, 0),
    ([], 0),
    ({}, 0),
    (True, 0),
    ("30", 30000),
    (0.0001, 0),
    (1e30, _DAY_MS),
    (90000, _DAY_MS),
    (86400, _DAY_MS),
    (120, 120000),
)
_OFF_DELAYS = tuple(raw for raw, ms in _DELAY_CASES if ms == 0)


def _set_delay(window, raw) -> None:
    window.config = {"agent": {"wall_toast_after_s": raw}}


def _pause_your_turn(*, kind: str = "captcha", url: str = "https://example.com/wall") -> Event:
    return Event(
        EventType.TURN_PAUSE,
        {"reason": "your_turn", "kind": kind, "url": url},
    )


def test_wall_toast_delay_ms_float_overflow_after_scale_is_off() -> None:
    from arelis.ui.event_host import _wall_toast_delay_ms

    window = SimpleNamespace(config={"agent": {"wall_toast_after_s": 1e306}})
    assert _wall_toast_delay_ms(window) == 0


def test_turn_pause_your_turn_arms_toast_on_its_own(monkeypatch) -> None:
    from arelis.ui.event_host import dispatch_event

    _arm_hooks(monkeypatch)
    window = _window()
    dispatch_event(window, _pause_your_turn(kind="login"))
    timer = getattr(window, "_wall_toast_timer", None)
    assert timer is not None
    assert timer.active
    timer.fire()
    assert len(window.shown) == 1
    assert "Still waiting on you" in window.shown[0]


