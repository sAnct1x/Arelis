"""ARELIS_SURFACE=quick: one on-screen Qt Quick surface under the whole window (slice 1).

The default ("widget") keeps QQ3DAvatar: an offscreen QQuickRenderControl texture read back
to a QImage every frame, and the Filament orbit blitted by the window's paintEvent. Under
the flag the window's bottom layer is a single QQuickWidget (QuickSurface) that draws the
void, the Filament orbit (slice 2: ring, strands, dust and hub threads, and in idle the
v11b orbit tree, drawn by QuickOrbit.qml's shaders from OrbitState; the beads, stems and
tethers still a worker-painted image layer over them), and her Avatar.qml at her panel's
rect; nothing is
read back from the GPU. QuickSurfaceAvatar stands in for QQ3DAvatar with the same API.

QQuickWidget, not createWindowContainer: a container is a native child window, and on
Windows a native child always paints above its sibling widgets (airspace), so the tiles and
chrome could not sit over it. QQuickWidget renders into a texture the widget backing store
composites in z-order, so lower() really puts it under every other child.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QWidget

from arelis.ui.persona_face import qq3d_avatar
from arelis.ui.persona_face.qq3d_avatar import QML_DIR, QQ3DAvatar

SURFACE_ENV = "ARELIS_SURFACE"
SURFACE_QML = QML_DIR / "QuickSurface.qml"
_ORBIT_PROVIDER = "arelisorbit"
_TRACKED = (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide)


def surface_choice() -> tuple[str, str]:
    """('quick' | 'widget', source): process env first, then the saved user variable.

    Unset means quick: the tree orbit is the default. Any other value (widget) keeps the old orbit.
    """
    raw = os.environ.get(SURFACE_ENV, "").strip()
    source = "env"
    if not raw:
        raw = qq3d_avatar._saved_user_env(SURFACE_ENV).strip()
        source = "user-env" if raw else "default"
        if raw:
            os.environ[SURFACE_ENV] = raw  # read the registry once
    if not raw:
        return "quick", source
    return ("quick" if raw.lower() == "quick" else "widget"), source


def enabled() -> bool:
    return surface_choice()[0] == "quick"


def log_surface_choice() -> None:
    kind, source = surface_choice()
    logging.getLogger("arelis.avatar").info("[avatar] surface=%s source=%s", kind, source)


def _image_provider():
    from PySide6.QtQuick import QQuickImageProvider

    class OrbitImages(QQuickImageProvider):
        def __init__(self) -> None:
            super().__init__(QQuickImageProvider.ImageType.Image)
            self.images: dict[str, QImage] = {}

        def requestImage(self, id_, size, _requested):
            img = self.images.get(id_.split("/", 1)[0], QImage())
            if size is not None:
                size.setWidth(img.width())
                size.setHeight(img.height())
            return img

    return OrbitImages()


def _quick_widget_class():
    from PySide6.QtQuickWidgets import QQuickWidget

    class QuickSurface(QQuickWidget):
        """The window's single full-window Quick layer, kept lowest and window-sized."""

        def __init__(self, window: QWidget) -> None:
            from PySide6.QtQuick import QQuickWindow

            # Same rule as QQ3DAvatar: offscreen would pick software, which has no Quick 3D.
            # The RHI backend itself (QSG_RHI_BACKEND, D3D11 by default) is process-wide.
            if QQuickWindow.sceneGraphBackend() in ("", "software") and not os.environ.get(
                "QT_QUICK_BACKEND"
            ):
                QQuickWindow.setSceneGraphBackend("rhi")
            super().__init__(window)
            from PySide6.QtQuick3D import QQuick3D

            fmt = QQuick3D.idealSurfaceFormat()
            fmt.setAlphaBufferSize(8)
            self.setFormat(fmt)
            self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            self.setClearColor(QColor(Qt.GlobalColor.transparent))
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            import arelis.ui.persona_q3d.geometry  # noqa: F401  (registers LayerGeometry)

            self._images = _image_provider()
            self.engine().addImageProvider(_ORBIT_PROVIDER, self._images)
            self._image_n = 0
            from arelis.ui.persona_face.orbit_state import OrbitState

            self.orbit_state = OrbitState(self)
            self.rootContext().setContextProperty("orbitState", self.orbit_state)
            # No pipeline cache here: a QQuickWidget renders with its top-level window's
            # backing-store QRhi, which Qt creates without EnablePipelineCacheDataSave and
            # without the QQuickGraphicsConfiguration (qquickwidget.cpp rhiConfig says so).
            # D3D11 only looks up its bytecode cache under that flag, so every start compiles
            # every pipeline on the GUI thread: the slower ready than the readback path.
            logging.getLogger("arelis.avatar").info(
                "[avatar] quick surface: no pipeline cache (QQuickWidget uses the window's QRhi)"
            )
            # ARELIS_FRAMETIME_LOG: the same frames.csv as the readback path, one line per
            # surface frame (her, the orbit image and the backdrop render together here).
            self._frames = qq3d_avatar.frame_log()
            if self._frames is not None:
                qq3d_avatar.attach_frame_log(self, self.quickWindow(), self._frames)
            # Her Loader3D is asynchronous: its incubation runs on this window's frames. A
            # QQuickWidget's engine gets no incubation controller by itself, so without this
            # the async load would never finish.
            self.engine().setIncubationController(self.quickWindow().incubationController())
            self.setSource(QUrl.fromLocalFile(str(SURFACE_QML)))
            self._window = window
            window._quick_surface = self
            window.installEventFilter(self)
            self.setGeometry(window.rect())
            self.lower()
            self.show()

        def eventFilter(self, obj, event) -> bool:
            if obj is self._window and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self.setGeometry(self._window.rect())
                self.lower()
            return False

        def slot(self):
            from PySide6.QtQuick import QQuickItem

            root = self.rootObject()
            return None if root is None else root.findChild(QQuickItem, "avatarSlot")

        def set_loading(self, on: bool) -> None:
            """The breathing loading state where she will stand (QuickSurface.qml)."""
            root = self.rootObject()
            if root is not None:
                root.setProperty("loading", bool(on))

        def set_void(self, color: QColor) -> None:
            root = self.rootObject()
            if root is not None:
                root.setProperty("voidColor", color)

        def set_orbit(self, image: QImage | None) -> None:
            """The worker's layer (beads, stems, tethers) over the GPU orbit; None clears it.

            The image covers only the box those fill (QImage.offset() in window px), so the
            overlay is placed there rather than stretched over the window.
            """
            root = self.rootObject()
            if root is not None and image is not None and not image.isNull():
                dpr = image.devicePixelRatio() or 1.0
                off = image.offset()
                root.setProperty(
                    "orbitRect",
                    QRectF(off.x(), off.y(), image.width() / dpr, image.height() / dpr),
                )
            self._set_image("orbit", "orbitSource", image)

        def set_backdrop(self, image: QImage | None) -> None:
            """Night and Sodium: the room's atmosphere under everything; None clears it."""
            self._set_image("backdrop", "backdropSource", image)

        def _set_image(self, name: str, prop: str, image: QImage | None) -> None:
            root = self.rootObject()
            if root is None:
                return
            if image is None or image.isNull():
                self._images.images.pop(name, None)
                if root.property(prop):
                    root.setProperty(prop, "")
                return
            self._images.images[name] = image
            self._image_n += 1
            root.setProperty(prop, f"image://{_ORBIT_PROVIDER}/{name}/{self._image_n}")

    return QuickSurface


_SURFACE_CLASS = None


def surface_for(window: QWidget):
    """The window's QuickSurface, made on first ask."""
    global _SURFACE_CLASS
    have = getattr(window, "_quick_surface", None)
    if have is not None:
        return have
    if _SURFACE_CLASS is None:
        _SURFACE_CLASS = _quick_widget_class()
    return _SURFACE_CLASS(window)


class QuickSurfaceAvatar(QWidget):
    """QQ3DAvatar's API, drawn by the window's QuickSurface instead of a readback.

    This widget paints nothing: it only holds her place in the panel layout, and her scene
    on the surface follows its rect (mapped to the window) and its visibility.
    """

    failed = Signal(str)
    ready = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._ready = False
        self._dead = False
        self._state = "idle"
        self._level = -1.0
        self.root = None
        self.surface = None
        self._watched: list[QWidget] = []
        QTimer.singleShot(0, self._attach)

    # ---- attach and place ----

    def _attach(self) -> None:
        if self._dead or self.root is not None or not self.isVisible():
            return
        from PySide6.QtQml import QQmlComponent

        from arelis.ui.persona_face.panel import alog

        top = self.window()
        if top is self:
            return
        try:
            self.surface = surface_for(top)
        except Exception as exc:
            self._fail(f"quick surface failed: {exc}")
            return
        slot = self.surface.slot()
        if slot is None:
            errs = "; ".join(e.toString() for e in self.surface.errors()) or "no surface root"
            self._fail(f"surface error: {errs}")
            return
        model = qq3d_avatar.model_path()
        alog("qq3d load", path=model, engine="qq3d", surface="quick")
        component = QQmlComponent(self.surface.engine(), QUrl.fromLocalFile(str(qq3d_avatar.ENTRY)))
        root = component.create() if component.isReady() else None
        if root is None:
            errs = "; ".join(e.toString() for e in component.errors()) or "no root"
            self._fail(f"scene error: {errs}")
            return
        self._component = component
        root.setParentItem(slot)
        self.root = root
        self._slot = slot
        self._watch_ancestors()
        self._place()
        self._apply_theme()
        root.setProperty("avatarState", self._state)
        root.setProperty("speaking", self._state == "speaking")
        if self._level >= 0:
            root.setProperty("level", self._level)
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._on_status)
        self._poll.start()
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(lambda: self._fail("scene did not report ready"))
        self._deadline.start(qq3d_avatar._READY_TIMEOUT_MS)
        self.surface.set_loading(True)
        root.chestChanged.connect(self._on_chest)
        root.setProperty("modelSource", QUrl.fromLocalFile(str(model)))

    def _watch_ancestors(self) -> None:
        for w in self._watched:
            w.removeEventFilter(self)
        self._watched = []
        w = self.parentWidget()
        while w is not None:
            w.installEventFilter(self)
            self._watched.append(w)
            if w.isWindow():
                break
            w = w.parentWidget()

    def eventFilter(self, obj, event) -> bool:
        if event.type() in _TRACKED:
            self._place()
        return False

    def _place(self) -> None:
        slot = getattr(self, "_slot", None)
        if slot is None or self.surface is None:
            return
        top = self.surface.parentWidget()
        pos = self.mapTo(top, QPointF(0, 0)) if top is not None else QPointF(0, 0)
        w, h = max(1, self.width()), max(1, self.height())
        slot.setX(pos.x())
        slot.setY(pos.y())
        slot.setWidth(w)
        slot.setHeight(h)
        slot.setVisible(self.isVisible() and not self._dead)
        if self.root is not None:
            self.root.setWidth(w)
            self.root.setHeight(h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._place()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.root is None:
            self._attach()
        self._place()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._place()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ParentChange and self.root is not None:
            self._watch_ancestors()
            self._place()
        return super().event(event)

    def closeEvent(self, event) -> None:
        self._drop()
        super().closeEvent(event)

    def _drop(self) -> None:
        # A host swapped out mid-load (a theme switch): its poll and deadline stop, and the
        # window's loading veil goes, or it breathes on forever over the next host.
        for t in ("_poll", "_deadline"):
            timer = getattr(self, t, None)
            if timer is not None:
                timer.stop()
        if self.surface is not None and not self._ready:
            self.surface.set_loading(False)
        slot = getattr(self, "_slot", None)
        if slot is not None:
            slot.setVisible(False)
        root, self.root = self.root, None
        if root is not None:
            root.setParentItem(None)
            root.deleteLater()

    def deleteLater(self) -> None:  # panel swaps hosts with hide() + deleteLater()
        self._drop()
        super().deleteLater()

    # ---- the API callers use: QQ3DAvatar's own methods ----

    is_ready = QQ3DAvatar.is_ready
    set_state = QQ3DAvatar.set_state
    set_level = QQ3DAvatar.set_level
    refit = QQ3DAvatar.refit
    refresh_theme_icons = QQ3DAvatar.refresh_theme_icons
    _apply_theme = QQ3DAvatar._apply_theme
    _set = QQ3DAvatar._set

    def _on_status(self, *args) -> None:
        QQ3DAvatar._on_status(self, *args)
        if self._ready and self.surface is not None:
            self.surface.set_loading(False)

    def _on_chest(self) -> None:
        """Her chest bone, mapped to the window: where the Filament chat strand starts."""
        root, slot = self.root, getattr(self, "_slot", None)
        field = getattr(self.window(), "_filament", None)
        if root is None or slot is None or field is None or not hasattr(field, "set_heart"):
            return
        c = root.property("chest")
        if c is None or c.x() < 0:
            field.set_heart(None)
            return
        field.set_heart(QPointF(slot.x() + c.x(), slot.y() + c.y()))

    def _fail(self, reason: str) -> None:
        if not self._dead:
            slot = getattr(self, "_slot", None)
            if slot is not None:
                slot.setVisible(False)
            if self.surface is not None:
                self.surface.set_loading(False)
        QQ3DAvatar._fail(self, reason)
