"""The one writer of a dock's paint surface and window chrome.

The invariant every ghosting fix has been reaching for is a single sentence: a
floating dock is its own top-level HWND, and a top-level HWND carrying
WA_TranslucentBackground is a Windows layered window, whose bitmap belongs to
the OS rather than to Qt. The OS keeps that bitmap across hide, show and
resize, and presents it again before Qt has run a single paintEvent. One frame
of translucency on a float is therefore enough to buy a stale copy of the panel
that outlives whatever caused it — the ghost.

Six functions across three modules used to write WA_TranslucentBackground,
WA_OpaquePaintEvent and autoFillBackground on the same four widgets (the dock,
its shell, the InstrumentPanel, and any GlassDockContent under it), in
different orders, two of them from QTimer.singleShot callbacks that ran after
the window was already mapped. An invariant that short cannot be held by six
cooperating writers, so it is held here instead and everyone else calls in.

The split between the two public functions is load-bearing:

``apply_dock_surface`` only ever writes attributes. It never shows, hides or
reparents anything, so it is safe to call at any point, including in the middle
of a drag.

``apply_dock_chrome`` swaps window flags, which destroys and re-creates the
native window. That cannot happen mid-drag without dropping the mouse grab, so
it is the half that sometimes has to wait — and it applies the surface first,
so waiting is never the same as being translucent.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDockWidget, QWidget

from arelis.ui.theme import COLORS, GLASS
from arelis.ui.window_resize import enable_win32_resize_frame, release_child_hwnd

# Docked instruments are type in the void — no plate behind them. Floats are an
# opaque plate, because the alternative is compositing chat through the tile.
DOCKED_FILL_ALPHA = int(GLASS.get("fill_docked", 0))
FLOATING_FILL_ALPHA = int(GLASS.get("fill_float", 255))

FLOAT_MIN_SIZE = (360, 280)
DOCKED_MIN_WIDTH = 220
# Workspace is the one instrument with an editor in it; below this it is a slit.
WORKSPACE_MIN_HEIGHT = 160

def _float_dock_qss() -> str:
    return f"""
QDockWidget {{
    color: {COLORS["text"]};
    background-color: {COLORS["plate"]};
    border: none;
}}
"""


def _float_shell_qss() -> str:
    return f"background-color: {COLORS['plate']};"

_FLOAT_FLAGS = (
    Qt.WindowType.Window
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowSystemMenuHint
    | Qt.WindowType.WindowMinimizeButtonHint
    | Qt.WindowType.WindowMaximizeButtonHint
)

# Set by InstrumentPanel while a header drag is pulling a docked panel out.
_DRAG_UNDOCK = "_arelis_drag_undock"
# Read by _on_dock_visibility and _stack_left_instruments so the transient hide
# that setWindowFlags causes is not mistaken for the user closing a panel.
_CHROME_APPLYING = "_arelis_chrome_applying"


def _seal(widget: QWidget, opaque: bool) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, not opaque)
    widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, opaque)
    widget.setAutoFillBackground(opaque)
    # A QGraphicsOpacityEffect caches a pixmap of the widget. Left on across a
    # resize it re-presents the old one, which is the duplicate corner ticks and
    # leftover dock strips.
    if widget.graphicsEffect() is not None:
        widget.setGraphicsEffect(None)


def _instrument_panels(shell: QWidget) -> list[QWidget]:
    """Glass bodies under a dock shell.

    Matched on object name rather than isinstance so this module does not import
    InstrumentPanel, which imports the fill constants from here.
    """
    found = [c for c in shell.findChildren(QWidget) if c.objectName() == "GlassDockContent"]
    if shell.objectName() == "GlassDockContent":
        found.insert(0, shell)
    return found


def apply_dock_surface(dock: QDockWidget, floating: bool | None = None) -> None:
    """Set the whole dock subtree to the docked or floating surface.

    Idempotent and free of side effects on visibility, so it is always safe to
    call — which is what lets it run unconditionally on every topLevelChanged
    even when the chrome swap below has to be deferred.
    """
    if floating is None:
        floating = dock.isFloating()
    floating = bool(floating)
    mid_drag = bool(getattr(dock, _DRAG_UNDOCK, False))

    # Stylesheet before _seal, never after: QStyleSheetStyle polish clears
    # autoFillBackground on any widget it styles, on the assumption that the
    # sheet is painting the background itself. Sealing first and styling second
    # therefore un-sets half of what was just asked for.
    dock.setStyleSheet(_float_dock_qss() if floating else "")
    _seal(dock, floating)

    shell = dock.widget()
    if shell is not None:
        shell.setStyleSheet(_float_shell_qss() if floating else "")
        _seal(shell, floating)
        for panel in _instrument_panels(shell):
            _seal(panel, floating)
            set_alpha = getattr(panel, "set_fill_alpha", None)
            if callable(set_alpha):
                set_alpha(FLOATING_FILL_ALPHA if floating else DOCKED_FILL_ALPHA)
            # The docked header is what holds the mouse grab during a drag-undock.
            # Swapping it for float chrome hides the widget under the cursor and
            # the panel stops following it, so the header waits for mouse-up. The
            # surface above does not wait, which is the part that matters.
            swap_header = getattr(panel, "set_floating_layout", None)
            if callable(swap_header) and not mid_drag:
                swap_header(floating)
            panel.update()

    dock.update()


def apply_dock_chrome(dock: QDockWidget, floating: bool | None = None) -> None:
    """Give a dock its floating window flags, or take them away.

    Shell margins are not set here — ``_sync_panel_margins`` owns those, and it
    already zeroes them for a float.
    """
    if floating is None:
        floating = dock.isFloating()
    floating = bool(floating)

    apply_dock_surface(dock, floating)
    if getattr(dock, _DRAG_UNDOCK, False):
        return

    was_visible = dock.isVisible()
    setattr(dock, _CHROME_APPLYING, True)
    try:
        # Qt's own title bar stays zero-height in both states; the visible
        # chrome is in-panel, so the tile reads as one slab.
        stub = dock.titleBarWidget()
        if stub is None or stub.maximumHeight() != 0:
            stub = QWidget(dock)
            stub.setFixedHeight(0)
            dock.setTitleBarWidget(stub)

        if floating:
            if int(dock.windowFlags()) != int(_FLOAT_FLAGS):
                dock.setWindowFlags(_FLOAT_FLAGS)
                # setWindowFlags throws the native window away. The next show
                # builds a new one from the current attributes, so they have to
                # be re-stated here or the fresh HWND is created layered and
                # Windows starts caching its bitmap again.
                apply_dock_surface(dock, True)
            dock.setMinimumSize(*FLOAT_MIN_SIZE)
            if was_visible:
                dock.show()
                dock.raise_()
            enable_win32_resize_frame(dock)
        else:
            dock.setMinimumWidth(DOCKED_MIN_WIDTH)
            name = (dock.objectName() or "").lower()
            dock.setMinimumHeight(WORKSPACE_MIN_HEIGHT if "workspace" in name else 0)
            # A float had its own HWND. Back in the glass that HWND is a child
            # and would paint a second copy of the panel, offset by the dock origin.
            release_child_hwnd(dock)
            if was_visible and not dock.isVisible():
                dock.show()
    finally:
        def _end_guard(d: QDockWidget = dock, want: bool = was_visible) -> None:
            setattr(d, _CHROME_APPLYING, False)
            if want and not d.isVisible():
                d.show()
                d.raise_()
            if d.isFloating():
                # WS_THICKFRAME needs a live HWND, so this is the earliest point
                # it can be added after a flag swap re-created the window.
                enable_win32_resize_frame(d)

        QTimer.singleShot(0, _end_guard)


def begin_drag_undock(dock: QDockWidget) -> None:
    """Hold the flag swap and the header swap until the drag ends."""
    setattr(dock, _DRAG_UNDOCK, True)


def end_drag_undock(dock: QDockWidget) -> bool:
    """Release the hold and report whether there was one to release."""
    if not getattr(dock, _DRAG_UNDOCK, False):
        return False
    setattr(dock, _DRAG_UNDOCK, False)
    return True


def chrome_applying(dock: QDockWidget) -> bool:
    """True while a flag swap is mid-flight and hides are not user intent."""
    return bool(getattr(dock, _CHROME_APPLYING, False))
