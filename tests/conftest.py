from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Point the whole suite at a throwaway data root, at import time, before anything else.
#
# This is not belt-and-braces. Until it existed, a test that forgot to sandbox itself wrote
# into the developer's live profile: real memory.db, real action_ledger.jsonl, real
# tool_cache. It was found by noticing that a test run had appended a fixture email and a
# pytest temp path to a ledger of real actions. Ten test modules set ARELIS_DATA_DIR
# themselves; the rest trusted the environment, and the environment was somebody's Arelis.
#
# Import time rather than an autouse fixture, and that ordering is the whole trick. Modules
# resolve some paths once -- jobs.store computes JOBS_PATH, memory.store computes its
# default -- and those run when the test modules are imported during collection, which is
# before any fixture. A fixture would be correct and useless. conftest is imported before
# test modules, so this is early enough to be believed.
#
# Unconditional, including over an ARELIS_DATA_DIR that is already set, because the value
# most likely to be sitting in the environment is the one pointing at the real profile.
# Tests that need a specific root still monkeypatch it, and the handful that assert what a
# checkout does without an override still delete it.
# Resolved, and that matters on Windows. An account whose name is longer than eight
# characters also gets an 8.3 short alias, and tempfile.gettempdir() reports the aliased
# spelling while resolve() expands it. Two strings, one directory -- so anything that
# canonicalises a path before comparing it disagrees with anything that does not, which
# failed two tests on every CI runner and on no machine whose username is short enough to
# have no alias at all. The runner accounts are the common case, not an exotic one.
_TESTS_DATA_ROOT = Path(tempfile.mkdtemp(prefix="arelis-tests-")).resolve()
os.environ["ARELIS_DATA_DIR"] = str(_TESTS_DATA_ROOT)


def pytest_sessionfinish(session, exitstatus):
    """Delete the throwaway root, and do not fail the run if Windows will not let go.

    ignore_errors because a test that left a SQLite connection open holds a lock Windows
    honours, and a suite that passed must not report failure over scratch files in TEMP.
    """
    shutil.rmtree(_TESTS_DATA_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def qt_app():
    """One offscreen QApplication for the widget tests.

    Offscreen because these run in CI and over SSH, where there is no display
    and Qt would otherwise abort the whole process rather than fail a test.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def arelis_window(qt_app):
    """Build ArelisWindows that are taken apart when the test ends.

    Sixteen existing tests build one by hand and hide() it in a finally block,
    which is where this whole class of crash came from. New tests should ask for
    this instead.
    """
    import asyncio

    from arelis.core.bus import EventBus

    made = []

    def _make(config: dict | None = None):
        from arelis.ui.app import ArelisWindow, BusBridge

        base = {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        }
        base.update(config or {})
        window = ArelisWindow(base, BusBridge(), asyncio.new_event_loop(), EventBus())
        made.append(window)
        return window

    yield _make

    for window in made:
        try:
            window.dispose()
            window.loop.close()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _dispose_arelis_windows():
    """Take each window apart after the test that built it.

    Sixteen tests build an ArelisWindow and only hide() it. Hiding releases
    nothing: the application-wide event filter stays installed, nine timers keep
    running, and the single-shots the constructor schedules at 0, 40, 80 and 250ms
    are still in flight. So the suite ran with a growing pile of live windows, and
    somewhere past halfway one of those late callbacks reached a widget whose C++
    half a later drain had deleted, and the process died with an access violation
    rather than a failure.

    That is why it looked like a flake that moved: which test was executing when
    the pile got big enough depended on file order, and adding a test file moved
    it. It reproduced with all five of the heavy widget files and with no pair of
    them, which is the signature of accumulation rather than interaction.

    Autouse and cheap: for the ~800 tests that never touch Qt this is one
    ``sys.modules`` lookup.
    """
    yield

    import sys

    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    window_cls = getattr(sys.modules.get("arelis.ui.app"), "ArelisWindow", None)

    for widget in list(app.topLevelWidgets()):
        try:
            if window_cls is not None and isinstance(widget, window_cls):
                widget.dispose()
                continue
            # Chat panels, orbit faces and camera docks are built bare by other
            # tests, and they run timers too — the caret blink, the shimmer, the
            # orbit animation. A widget nobody owns is a widget nobody stops.
            for timer in widget.findChildren(QTimer):
                timer.stop()
            widget.hide()
            widget.deleteLater()
        except Exception:
            # A test that already tore its own window down is not worth failing
            # here, and the drain below still runs.
            pass

    # deleteLater only queues. Without draining it the objects survive until the
    # next event loop that happens to run, which is how a stale delete ended up
    # inside an unrelated test's processEvents().
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
