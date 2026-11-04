"""The app-wide event filters, installed here so a heavy QML build can run without them.

Every Python filter on the QApplication sees every event sent to every GUI-thread object,
and each call wraps the receiver and the event in Python. Her Quick 3D scene creates about
86,000 QObjects (Timeline keyframes) in one synchronous step, each sending ChildAdded: with
the window's five filters that was 400,000 Python calls, seconds of a frozen GUI thread on
first load. ``quiet()`` lifts the filters for such a step. Nothing else is delivered while it
runs (no event loop turns inside), so no filter misses an event it cares about.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

_FILTERS: list = []  # installed order, so quiet() puts them back as they were


def install(app, filt) -> None:
    """``app.installEventFilter(filt)``, remembered so quiet() can lift it."""
    app.installEventFilter(filt)
    if not any(f is filt for f in _FILTERS):
        _FILTERS.append(filt)


def remove(app, filt) -> None:
    app.removeEventFilter(filt)
    _FILTERS[:] = [f for f in _FILTERS if f is not filt]


@contextmanager
def quiet() -> Iterator[None]:
    """Run a synchronous block with the app filters lifted; they return in their order."""
    import shiboken6
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance()
    live = [f for f in _FILTERS if shiboken6.isValid(f)]
    _FILTERS[:] = live
    if app is None or not live:
        yield
        return
    for f in live:
        app.removeEventFilter(f)
    try:
        yield
    finally:
        for f in live:
            if shiboken6.isValid(f):
                app.installEventFilter(f)
