"""The order `_construct_shell` builds its 54 subsystems in is load-bearing.

Qt construction order breaks at runtime, not at import, and often only on one
path — a widget parented before its layout, a signal connected before its
receiver exists, a subsystem reading another's attribute during `__init__`.
Before the split this order was implicit in line position inside one ~400-line
method, so there was nothing to read and nothing to check.

The phases carry `assert hasattr(...)` guards naming what they need. Those are
documentation that happens to execute; the real edges are below, because an
assert only fires on the path that runs and these tests are what notice when
the order changes.

`test_a_reordered_phase_is_caught` is the one that matters. Everything else
here passes on a correctly ordered tree by construction, so without it a
reorder that happens not to crash — two phases that are independent today and
grow a dependency tomorrow — would sail through.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from arelis.ui.app import ArelisWindow

# Phase -> the phases that must already have run. Read off the assert guards
# in window_build.py; keep the two in step.
REQUIRES: dict[str, tuple[str, ...]] = {
    "_build_chrome": ("_build_core_state",),
    "_build_stage_and_chat": ("_build_core_state",),
    "_build_instruments": ("_build_core_state", "_build_stage_and_chat"),
    "_build_docks": ("_build_instruments",),
    "_build_timers_and_state": ("_build_core_state",),
    "_build_secondary_windows": ("_build_instruments", "_build_timers_and_state"),
    "_connect_signals_and_bind": ("_build_docks", "_build_secondary_windows"),
}

PHASES = ("_build_core_state", *[p for p in REQUIRES if p != "_build_core_state"])


def _window() -> ArelisWindow:
    bridge = Mock()
    bridge.event_arrived = Mock()
    return ArelisWindow({"ui": {}}, bridge, None, Mock())


def test_the_shell_builds_at_all(qt_app) -> None:
    win = _window()
    assert win.conversation is not None
    assert win.think_dock is not None


def test_every_phase_runs_once_and_after_what_it_needs(qt_app, monkeypatch) -> None:
    """Records the real call order rather than trusting the source reads right."""
    seen: list[str] = []
    for name in PHASES:
        original = getattr(ArelisWindow, name)

        def wrapper(self, *a, _name=name, _orig=original, **kw):
            seen.append(_name)
            return _orig(self, *a, **kw)

        monkeypatch.setattr(ArelisWindow, name, wrapper)

    _window()

    assert sorted(seen) == sorted(PHASES), f"a build phase was skipped or run twice: {seen}"
    for phase, needs in REQUIRES.items():
        for need in needs:
            assert seen.index(need) < seen.index(phase), (
                f"{phase} ran before {need}, which it reads from"
            )


@pytest.mark.parametrize(
    ("phase", "needed"),
    [(p, n) for p, needs in REQUIRES.items() for n in needs],
)
def test_a_reordered_phase_is_caught(qt_app, monkeypatch, phase, needed) -> None:
    """Every edge in REQUIRES is real: skip the dependency and construction dies.

    Proof the table is not decoration. An edge nobody actually depends on would
    let construction finish here, and this test would be the thing that says so
    rather than a comment drifting out of date.
    """
    monkeypatch.setattr(ArelisWindow, needed, lambda self, *a, **kw: None)
    with pytest.raises((AssertionError, AttributeError, TypeError)):
        _window()
