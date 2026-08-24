"""Ask the running window what it actually contains.

Written because the duplicate-paint bug survived three diagnoses made by reading
screenshots. Each one fit the picture and none survived measurement: a layered
HWND caching its bitmap, a WM_NCCALCSIZE client blit, and two processes. What
was missing every time was the widget tree, which only the process has.

What is worth reporting is set by what has already been eliminated. There is one
visible top-level window, one ArelisWindow, one ConversationStage and one
HistoryPanel, and no production code renders a widget into another. So a second
live copy of a subtree has to come from one of:

  * a native child window — calling winId() on a child promotes it to its own
    HWND, and enable_win32_resize_frame then puts WS_THICKFRAME on it. A child
    HWND with a non-client frame is composited separately from its parent's
    backing store and offset by the frame it just grew. Child HWNDs do not
    appear in EnumWindows, which is why the outside-in scan came back with one
    window while the screen clearly had two of everything.

  * a QGraphicsEffect, which renders its source into a pixmap and draws that.
    Wrong source coordinates put the pixmap beside the live widget, and because
    it is re-rendered every frame the copy has live text in it.

  * a widget that is in the tree twice, or a second instance nobody meant to
    build.

Each section below answers exactly one of those, so the output either names the
cause or removes it from the list. Positions are mapped to window coordinates,
because the offsets seen on screen match parent-chain origins and that is the
thing to compare against.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)

# Reported by class name so this module imports nothing from the panels and
# cannot become a source of import cycles in a package this size.
_WATCHED = (
    "ArelisWindow",
    "ConversationStage",
    "ChatPanel",
    "OrbitIdle",
    "OrbitCanvas",
    "HistoryPanel",
    "InstrumentPanel",
    "StageBackground",
    "GlassDockWidget",
    "TitleBar",
    "_ComposerLineEdit",
)


def _where(widget: QWidget, root: QWidget) -> str:
    """Geometry in root coordinates, plus the chain that positions it."""
    try:
        top_left = widget.mapTo(root, widget.rect().topLeft())
        pos = f"{top_left.x()},{top_left.y()}"
    except Exception:
        pos = "unmapped"
    return f"{pos} {widget.width()}x{widget.height()}"


def _attrs(widget: QWidget) -> str:
    """The attributes that decide how a widget is composited.

    WA_NativeWindow is the one that matters most: set explicitly it means
    something asked for this HWND, while a native widget without it was
    promoted by Qt to keep z-order against a native sibling. Telling those two
    apart is the difference between fixing a caller and fixing a cascade.
    """
    flags = {
        "native_attr": Qt.WidgetAttribute.WA_NativeWindow,
        "translucent": Qt.WidgetAttribute.WA_TranslucentBackground,
        "opaque_paint": Qt.WidgetAttribute.WA_OpaquePaintEvent,
        "paint_on_screen": Qt.WidgetAttribute.WA_PaintOnScreen,
        "no_native_ancestors": Qt.WidgetAttribute.WA_DontCreateNativeAncestors,
    }
    on = [name for name, attr in flags.items() if widget.testAttribute(attr)]
    if widget.autoFillBackground():
        on.append("autofill")
    return ",".join(on) if on else "-"


def _chain(widget: QWidget) -> str:
    names: list[str] = []
    node: QWidget | None = widget
    while node is not None and len(names) < 12:
        label = type(node).__name__
        if node.objectName():
            label += f"#{node.objectName()}"
        names.append(label)
        node = node.parentWidget()
    return " < ".join(names)


def report_lines(window: QWidget) -> list[str]:
    """The report as lines, so tests can assert on it without a log handler."""
    out: list[str] = []
    app = QApplication.instance()

    out.append("--- surface report ---")

    tops = [w for w in (app.topLevelWidgets() if app is not None else []) if not w.isHidden()]
    out.append(f"visible top-level widgets: {len(tops)}")
    for w in tops:
        # An empty mask means the rounded corners are coming from translucency
        # rather than from a region, which decides whether the layered surface
        # can be given up.
        mask = w.mask()
        out.append(
            f"  top {type(w).__name__}#{w.objectName()} "
            f"geo={w.geometry().getRect()} flags={int(w.windowFlags()):#x} "
            f"native={w.internalWinId() or 0:#x} "
            f"mask={'none' if mask.isEmpty() else mask.boundingRect().getRect()} "
            f"attrs={_attrs(w)}"
        )

    # Native child windows. A child with its own HWND is composited on its own,
    # so this list should be empty or contain only deliberate cases.
    natives = [
        w
        for w in window.findChildren(QWidget)
        if w.internalWinId() and w.window() is not w
    ]
    out.append(f"native child windows: {len(natives)}")
    for w in natives:
        out.append(f"  native {_where(w, window)} attrs={_attrs(w)} {_chain(w)}")

    effects = [w for w in window.findChildren(QWidget) if w.graphicsEffect() is not None]
    if window.graphicsEffect() is not None:
        effects.insert(0, window)
    out.append(f"widgets carrying a graphics effect: {len(effects)}")
    for w in effects:
        out.append(
            f"  effect {type(w.graphicsEffect()).__name__} on "
            f"{_where(w, window)} {_chain(w)}"
        )

    # Duplicate instances. More than one of any of these is the answer on its own.
    out.append("instance counts:")
    for name in _WATCHED:
        found = [
            w
            for w in window.findChildren(QWidget)
            if type(w).__name__ == name
        ]
        if type(window).__name__ == name:
            found.insert(0, window)
        if not found:
            continue
        out.append(f"  {name}: {len(found)}")
        if len(found) > 1:
            for w in found:
                out.append(
                    f"    #{len(out)} {_where(w, window)} "
                    f"hidden={w.isHidden()} {_chain(w)}"
                )
    return out


def log_report(window: QWidget, *, tag: str = "") -> None:
    """Write the report at INFO so it lands in logs/arelis.log."""
    try:
        lines = report_lines(window)
    except Exception as exc:  # a diagnostic must never take the window down
        log.warning("surface report failed: %s", exc)
        return
    label = f" ({tag})" if tag else ""
    log.info("Surface report%s:\n%s", label, "\n".join(lines))
