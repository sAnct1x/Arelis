"""Keep the Python wrapper of every main-thread QObject that gains a child.

Each Python application event filter (theme colour-on-show, click-to-front, the widget
mirror, the window's own) makes PySide wrap the receiver of every event. A QObject made
in C++ gets a fresh wrapper each time, found through Shiboken's type heuristics
(dynamic_cast walks), and drops it on return. Her avatar's incubation creates tens of
thousands of QQuickKeyframe children, each a ChildAdded to its group: on the box that
was ~9 s of the GUI thread inside shiboken, before her first frame and her ready.

Pinning the group on its first ChildAdded makes every later lookup a hash hit. The pin
goes when the object is destroyed. Only keyframe groups: a widget gets ChildAdded inside
its own constructor, while its dynamic type is still a base class, and a pinned wrapper
of that base type would stick (QComboBox.view() came back a QWidget).
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject

_CHILD_ADDED = QEvent.Type.ChildAdded
_GROUP = "QQuickKeyframeGroup"


class _Pin(QObject):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.pinned: dict[int, QObject] = {}

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() == _CHILD_ADDED:
            key = id(obj)
            if key not in self.pinned and obj.metaObject().className() == _GROUP:
                self.pinned[key] = obj
                obj.destroyed.connect(lambda *_a, k=key: self.pinned.pop(k, None))
        return False


def install() -> None:
    app = QCoreApplication.instance()
    if app is None or app.property("_arelis_wrapper_pin"):
        return
    pin = _Pin(app)
    app.installEventFilter(pin)
    app.setProperty("_arelis_wrapper_pin", True)
    app._arelis_wrapper_pin = pin  # type: ignore[attr-defined]
