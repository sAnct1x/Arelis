"""Local tray toast after a browser wall wait. No network, no extra packages."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_resume_or_cancel_before_delay_gives_no_toast(monkeypatch) -> None:
    from arelis.ui.event_host import dispatch_event

    _arm_hooks(monkeypatch)
    window = _window()
    dispatch_event(window, _your_turn())
    timer = window._wall_toast_timer
    dispatch_event(
        window,
        Event(EventType.TURN_RESUME, {"reason": "wall_cleared"}),
    )
    timer.fire()
    assert window.shown == []

    window2 = _window()
    dispatch_event(window2, _your_turn())
    timer2 = window2._wall_toast_timer
    dispatch_event(window2, Event(EventType.TURN_CANCEL, {}))
    timer2.fire()
    assert window2.shown == []


def test_second_same_wall_event_does_not_rearm(monkeypatch) -> None:
    from arelis.ui.event_host import dispatch_event

    _arm_hooks(monkeypatch)
    window = _window()
    dispatch_event(window, _your_turn())
    first = window._wall_toast_timer
    first_interval = first.interval_ms
    dispatch_event(window, _your_turn())
    dispatch_event(
        window,
        Event(EventType.TURN_PAUSE, {"reason": "your_turn", "kind": "captcha"}),
    )
    assert window._wall_toast_timer is first
    assert first.interval_ms == first_interval
    first.fire()
    assert len(window.shown) == 1


def test_wall_toast_after_s_zero_is_off(monkeypatch) -> None:
    from arelis.ui.event_host import dispatch_event

    _arm_hooks(monkeypatch)
    window = _window(delay_s=0)
    dispatch_event(window, _your_turn())
    assert getattr(window, "_wall_toast_timer", None) is None
    assert window.shown == []


def test_missing_tray_does_not_raise(monkeypatch) -> None:
    from arelis.ui.event_host import dispatch_event

    _arm_hooks(monkeypatch)
    window = _window()
    window._tray = None
    dispatch_event(window, _your_turn())
    window._wall_toast_timer.fire()
    assert window.shown == []


def test_assistant_done_and_error_cancel_the_timer(monkeypatch) -> None:
    from arelis.ui.event_host import dispatch_event

    _arm_hooks(monkeypatch)
    window = _window()
    window._mobile_foreign = True
    dispatch_event(window, _your_turn())
    timer = window._wall_toast_timer
    dispatch_event(window, Event(EventType.ASSISTANT_DONE, {"text": ""}))
    timer.fire()
    assert window.shown == []

    window2 = _window()
    window2._mobile_foreign = True
    dispatch_event(window2, _your_turn())
    timer2 = window2._wall_toast_timer
    dispatch_event(window2, Event(EventType.ERROR, {"message": "nope"}))
    timer2.fire()
    assert window2.shown == []


def test_wall_toast_modules_do_not_import_network_or_toast_libs() -> None:
    for name in ("event_host.py", "notify_host.py"):
        found = _imports_of(_UI / name)
        bad = found & _FORBIDDEN
        assert not bad, f"{name} imports {sorted(bad)}"


def test_default_config_has_wall_toast_after_s() -> None:
    text = (
        Path(__file__).resolve().parents[1] / "arelis" / "config" / "default.yaml"
    ).read_text(encoding="utf-8")
    assert "wall_toast_after_s: 120" in text


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


@pytest.mark.parametrize("raw, expected", _DELAY_CASES)
def test_wall_toast_delay_ms_values(raw, expected) -> None:
    from arelis.ui.event_host import _wall_toast_delay_ms

    window = SimpleNamespace(config={"agent": {"wall_toast_after_s": raw}})
    assert _wall_toast_delay_ms(window) == expected


@pytest.mark.parametrize(
    "raw",
    (10**400, -(10**400)),
    ids=("10**400", "neg-10**400"),
)
def test_wall_toast_delay_ms_huge_int_is_off(raw: int) -> None:
    from arelis.ui.event_host import _wall_toast_delay_ms

    window = SimpleNamespace(config={"agent": {"wall_toast_after_s": raw}})
    assert _wall_toast_delay_ms(window) == 0


def test_wall_toast_delay_ms_float_overflow_after_scale_is_off() -> None:
    from arelis.ui.event_host import _wall_toast_delay_ms

    window = SimpleNamespace(config={"agent": {"wall_toast_after_s": 1e306}})
    assert _wall_toast_delay_ms(window) == 0


def test_wall_toast_delay_ms_agent_section_attribute_error_is_off() -> None:
    from arelis.ui.event_host import _wall_toast_delay_ms

    class _Config:
        def get(self, *_args: object, **_kwargs: object) -> object:
            raise AttributeError("agent")

    assert _wall_toast_delay_ms(SimpleNamespace(config=_Config())) == 0


@pytest.mark.parametrize(
    "raw",
    (10**400, -(10**400)),
    ids=("10**400", "neg-10**400"),
)
def test_huge_wall_toast_delay_does_not_escape_dispatch(
    monkeypatch: pytest.MonkeyPatch, raw: int
) -> None:
    from arelis.ui.event_host import dispatch_event

    _arm_hooks(monkeypatch)
    window = _window()
    _set_delay(window, raw)
    dispatch_event(window, _your_turn())
    assert getattr(window, "_wall_toast_pending", None) is None
    assert window.shown == []


@pytest.mark.parametrize(
    ("kind", "text"),
    (
        ("captcha", "Still waiting on you: captcha."),
        ("login", "Still waiting on you: sign in."),
        ("pay", "Still waiting on you: you click Pay."),
        ("stuck", "Still waiting on you. I cannot find the next step."),
        ("hands", "Still waiting on you: you have the mouse."),
        ("other", "Still waiting on you. The page is staying up."),
    ),
)
def test_wall_toast_message_says_the_wait_once(kind: str, text: str) -> None:
    from arelis.ui.event_host import _wall_toast_message

    got = _wall_toast_message(kind)
    assert got == text
    assert got.lower().count("your turn") == 0


def test_wall_toast_delay_ms_missing_key_and_none_config_default_to_120s() -> None:
    from arelis.ui.event_host import _wall_toast_delay_ms

    assert _wall_toast_delay_ms(SimpleNamespace(config={"agent": {}})) == 120000
    assert _wall_toast_delay_ms(SimpleNamespace(config=None)) == 120000
    assert _wall_toast_delay_ms(SimpleNamespace()) == 120000


@pytest.mark.parametrize("raw", _OFF_DELAYS)
@pytest.mark.parametrize(
    "make_event",
    (_your_turn, _pause_your_turn),
    ids=("YOUR_TURN", "TURN_PAUSE"),
)
def test_off_delay_does_not_raise_or_stick_pending(monkeypatch, raw, make_event) -> None:
    from arelis.ui.event_host import dispatch_event

    _arm_hooks(monkeypatch)
    window = _window()
    _set_delay(window, raw)
    dispatch_event(window, make_event())
    assert getattr(window, "_wall_toast_timer", None) is None or not window._wall_toast_timer.active
    assert getattr(window, "_wall_toast_pending", None) is None
    assert window.shown == []


def test_timer_start_raises_does_not_stick_pending(monkeypatch) -> None:
    from arelis.ui import event_host
    from arelis.ui.event_host import dispatch_event

    class BoomTimer(FakeTimer):
        def start(self, ms: int = 0) -> None:
            raise RuntimeError("start failed")

    monkeypatch.setattr(event_host, "QTimer", BoomTimer, raising=False)
    monkeypatch.setattr(
        event_host, "_arelis_window_is_active", lambda: False, raising=False
    )
    window = _window()
    dispatch_event(window, _your_turn())
    assert getattr(window, "_wall_toast_pending", None) is None
    assert window.shown == []


def test_toast_skipped_when_arelis_is_the_active_window(monkeypatch) -> None:
    from arelis.ui import event_host
    from arelis.ui.event_host import dispatch_event

    monkeypatch.setattr(event_host, "QTimer", FakeTimer, raising=False)
    monkeypatch.setattr(
        event_host, "_arelis_window_is_active", lambda: True, raising=False
    )
    window = _window()
    dispatch_event(window, _your_turn())
    timer = window._wall_toast_timer
    assert timer.active
    timer.fire()
    assert window.shown == []


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


def test_toast_reminder_show_message_and_missing_tray() -> None:
    from arelis.ui.notify_host import _toast_reminder

    shown: list[tuple] = []
    tray = SimpleNamespace(showMessage=lambda *a, **k: shown.append(a))
    _toast_reminder(SimpleNamespace(_tray=tray), "take the pizza out")
    assert len(shown) == 1
    assert shown[0][0] == "Arelis"
    assert shown[0][1] == "take the pizza out"

    _toast_reminder(SimpleNamespace(_tray=None), "take the pizza out")
    _toast_reminder(SimpleNamespace(), "take the pizza out")
    _toast_reminder(SimpleNamespace(_tray=tray), "")
    assert len(shown) == 1
