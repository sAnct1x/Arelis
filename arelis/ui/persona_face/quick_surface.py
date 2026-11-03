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
    """('quick' | 'widget', source): process env first, then the saved user variable."""
    raw = os.environ.get(SURFACE_ENV, "").strip()
    source = "env"
    if not raw:
        raw = qq3d_avatar._saved_user_env(SURFACE_ENV).strip()
        source = "user-env" if raw else "default"
        if raw:
            os.environ[SURFACE_ENV] = raw  # read the registry once
    return ("quick" if raw.lower() in ("quick", THREADED) else "widget"), source


# ARELIS_SURFACE=quickwindow (v11c, in progress): the same surface as a QQuickView on the
# threaded render loop with its own QRhi, so her frames and pipeline compiles leave the GUI
# thread and the pipeline cache works. Not the default yet. A native child window always
# paints over its sibling widgets, so every widget of the window (floats, chat stage, tiles,
# chrome, docks) would be hidden under it: WidgetMirror draws them onto the surface instead.
THREADED = "quickwindow"


def enabled() -> bool:
    return surface_choice()[0] == "quick"


def threaded() -> bool:
    return enabled() and os.environ.get(SURFACE_ENV, "").strip().lower() == THREADED


def pipeline_cache_path():
    from arelis.paths import cache_dir

    return cache_dir() / "quick" / "pipelines.bin"


def pipeline_cache_config():
    """A graphics configuration that loads and saves the QRhi pipeline cache.

    Only a QQuickWindow honours it (a QQuickWidget renders with its top-level window's
    QRhi, which never gets it): D3D11 then reuses compiled bytecode from the last run.
    """
    from PySide6.QtQuick import QQuickGraphicsConfiguration

    path = pipeline_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = QQuickGraphicsConfiguration()
    if path.is_file():
        cfg.setPipelineCacheLoadFile(str(path))
    cfg.setPipelineCacheSaveFile(str(path))
    return cfg


def write_pipeline_cache(data: bytes) -> bool:
    """Atomically write the QQuickView's pipeline cache plus its .key (as qq3d_avatar does)."""
    if not data:
        return False
    try:
        path = pipeline_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        path.with_suffix(".key").write_text(qq3d_avatar.pipeline_cache_key(), encoding="utf-8")
        return True
    except OSError:
        logging.getLogger("arelis.avatar").debug("quick pipeline cache not saved", exc_info=True)
        return False


_SET_VISIBLE = ("_ZN7QWindow10setVisibleEb", "?setVisible@QWindow@@QEAAX_N@Z")
_GUI_LIBS = ("libQt6Gui.so.6", "Qt6Gui.dll", "QtGui.framework/QtGui")


def gil_free_set_visible(window):
    """``f(on)`` calling QWindow::setVisible without the GIL, or the PySide call.

    Hiding a QQuickView on the threaded loop waits for its render thread, and that thread
    takes the GIL for Python slots and LayerGeometry: a PySide ``hide()`` deadlocks.
    """
    import ctypes

    import shiboken6

    lib = qq3d_avatar._load_library(_GUI_LIBS)
    fn = None
    for sym in _SET_VISIBLE:
        fn = getattr(lib, sym, None) if lib is not None else None
        if fn is not None:
            break
    if fn is None:
        logging.getLogger("arelis.avatar").warning("[avatar] QWindow::setVisible keeps the GIL")
        return window.setVisible
    fn.restype = None
    fn.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    this = ctypes.c_void_p(shiboken6.getCppPointer(window)[0])
    return lambda on: fn(this, bool(on))


def _container_accessible(key, obj):
    """The window container as a leaf for accessibility.

    Qt's container lists its QQuickView as child 0, but QAccessibleQuickWindow says its
    parent is the application, so UIA walkers bounce QuickSurfaceWindow <->
    QuickSurfaceContainer forever. The surface is transparent to input and has nothing
    to read (the widgets are mirrored, the real ones stay accessible), so drop it.
    """
    if obj is None or not isinstance(obj, QWidget) or obj.objectName() != "QuickSurfaceContainer":
        return None
    from PySide6.QtGui import QAccessible
    from PySide6.QtWidgets import QAccessibleWidget

    return QAccessibleWidget(obj, QAccessible.Role.Client)


_FACTORY = []


def _install_accessible_factory() -> None:
    if not _FACTORY:
        from PySide6.QtGui import QAccessible

        QAccessible.installFactory(_container_accessible)
        _FACTORY.append(_container_accessible)


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


class _SurfaceApi:
    """What the window and her host ask of the surface, whichever Quick host draws it."""

    def suspend(self) -> None:
        """Host hidden: stop rendering (QQuickView overrides)."""

    def resume(self) -> None:
        """Host shown again."""

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


def _quick_widget_class():
    from PySide6.QtQuickWidgets import QQuickWidget

    class QuickSurface(_SurfaceApi, QQuickWidget):
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
            if obj is self._window and event.type() == QEvent.Type.Show:
                self.resume()
            if obj is self._window and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self.setGeometry(self._window.rect())
                self.lower()
            return False

    return QuickSurface


_SURFACE_CLASS = None


def surface_for(window: QWidget):
    """The window's QuickSurface, made on first ask."""
    global _SURFACE_CLASS
    have = getattr(window, "_quick_surface", None)
    if have is not None:
        return have
    if _SURFACE_CLASS is None:
        _SURFACE_CLASS = _quick_window_class() if threaded() else _quick_widget_class()
    return _SURFACE_CLASS(window)


_TILE = 256  # logical px: a streamed token dirties one or two tiles, not the window

_TILE_QML = b"""
import QtQuick
Image { cache: false; smooth: false; fillMode: Image.Stretch; visible: source != "" }
"""


class WidgetMirror:
    """The window's widgets, drawn as the top layer of a QQuickView surface.

    Root cause it answers: a createWindowContainer child is a native window, and a native
    child always paints over its sibling widgets, so with ARELIS_SURFACE=quickwindow the
    whole widget layer was painted to the top-level window underneath it and never seen.
    The widgets stay real (the view is transparent for input, so clicks, keys and hover
    still reach them); only their pixels are re-rendered, into _TILE-sized images the
    surface shows over everything (the "widgets" item in QuickSurface.qml).

    #v11c-r2 streaming frames: one window-sized image per change meant a full-window
    QImage copy and a full-window texture upload for every token (at 2560x1392, 14 MB
    each, the upload inside the render thread's sync while the GUI thread waits on it),
    and every dirty widget painted twice: once into the window's backing store, which the
    native view covers, then again into the mirror. Now only the dirty tiles are rendered
    and uploaded, and the backing-store paint of a child widget is skipped.
    """

    def __init__(self, surface, window: QWidget, container: QWidget) -> None:
        from PySide6.QtCore import QObject
        from PySide6.QtGui import QRegion
        from PySide6.QtWidgets import QApplication

        self.surface = surface
        self.window = window
        self.container = container
        self.dirty = QRegion()
        self.tiles: dict[tuple[int, int], object] = {}  # (col, row) -> its Image item
        self._tile_n = 0
        self._dpr = 0.0
        self._component = None
        self._busy = False
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.flush)
        mirror = self

        class _Watch(QObject):
            def eventFilter(self, obj, event) -> bool:
                if event.type() == QEvent.Type.Paint and not mirror._busy:
                    return mirror._painted(obj, event)
                return False

        self._watch = _Watch()
        QApplication.instance().installEventFilter(self._watch)
        self.mark_all()

    def stop(self) -> None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self._watch)
        self._timer.stop()

    def _painted(self, obj, event) -> bool:
        """Note the damage; True eats a child's paint into the covered backing store."""
        if not isinstance(obj, QWidget) or obj is self.container:
            return False
        if obj is not self.window and obj.window() is not self.window:
            return False
        rect = event.rect()
        if obj is not self.window:
            rect = rect.translated(obj.mapTo(self.window, rect.topLeft()) - rect.topLeft())
        self.dirty += rect
        self._timer.start()
        # The window's own paintEvent only syncs the surface's void (it paints nothing
        # under the flag): let it run. A child's paint here lands under the native view.
        return obj is not self.window

    def mark_all(self) -> None:
        self.dirty += self.window.rect()
        self._timer.start()

    def _tile_item(self, key: tuple[int, int]):
        item = self.tiles.get(key)
        if item is not None:
            return item
        from PySide6.QtQml import QQmlComponent
        from PySide6.QtQuick import QQuickItem

        root = self.surface.rootObject()
        layer = None if root is None else root.findChild(QQuickItem, "widgets")
        if layer is None:
            return None
        if self._component is None:
            self._component = QQmlComponent(self.surface.engine())
            self._component.setData(_TILE_QML, QUrl())
        item = self._component.create()
        if item is None:
            return None
        item.setParentItem(layer)
        item.setX(key[0] * _TILE)
        item.setY(key[1] * _TILE)
        item.setWidth(_TILE)
        item.setHeight(_TILE)
        self.tiles[key] = item
        return item

    def flush(self) -> None:
        """Re-render the dirty tiles of the widget layer and hand each to the surface."""
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtGui import QRegion

        win = self.window
        if not win.isVisible():
            return
        dpr = win.devicePixelRatioF() or 1.0
        if dpr != self._dpr:
            self._dpr = dpr
            self.dirty = QRegion(win.rect())
        region, self.dirty = self.dirty & win.rect(), QRegion()
        if region.isEmpty():
            return
        box = region.boundingRect()
        side = int(_TILE * dpr)
        self._busy = True  # render() sends paint events of its own: not new damage
        try:
            for row in range(box.top() // _TILE, box.bottom() // _TILE + 1):
                for col in range(box.left() // _TILE, box.right() // _TILE + 1):
                    cell = QRect(col * _TILE, row * _TILE, _TILE, _TILE)
                    if not region.intersects(cell):
                        continue
                    item = self._tile_item((col, row))
                    if item is None:
                        continue
                    img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
                    img.setDevicePixelRatio(dpr)
                    img.fill(Qt.GlobalColor.transparent)
                    win.render(img, QPoint(0, 0), QRegion(cell), QWidget.RenderFlag.DrawChildren)
                    name = f"w{col}_{row}"
                    self.surface._images.images[name] = img
                    self._tile_n += 1
                    item.setProperty("source", f"image://{_ORBIT_PROVIDER}/{name}/{self._tile_n}")
        finally:
            self._busy = False

    def drop_tiles_outside(self) -> None:
        """After a shrink: tiles past the window's edge would show stale pixels."""
        w, h = self.window.width(), self.window.height()
        for key in [k for k in self.tiles if k[0] * _TILE >= w or k[1] * _TILE >= h]:
            item = self.tiles.pop(key)
            self.surface._images.images.pop(f"w{key[0]}_{key[1]}", None)
            item.setParentItem(None)
            item.deleteLater()


def _quick_window_class():
    from PySide6.QtQuick import QQuickView, QQuickWindow

    class QuickSurfaceWindow(_SurfaceApi, QQuickView):
        """The surface as a QQuickView in a window container (ARELIS_SURFACE=quickwindow)."""

        def __init__(self, window: QWidget) -> None:
            if QQuickWindow.sceneGraphBackend() in ("", "software") and not os.environ.get(
                "QT_QUICK_BACKEND"
            ):
                QQuickWindow.setSceneGraphBackend("rhi")
            super().__init__()
            from PySide6.QtQuick3D import QQuick3D

            # Before the scene graph starts: the cache file is read when the QRhi is made.
            self.setGraphicsConfiguration(pipeline_cache_config())
            fmt = QQuick3D.idealSurfaceFormat()
            fmt.setAlphaBufferSize(8)
            self.setFormat(fmt)
            self.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
            self.setColor(QColor(Qt.GlobalColor.transparent))
            self.setFlag(Qt.WindowType.WindowTransparentForInput, True)
            import arelis.ui.persona_q3d.geometry  # noqa: F401  (registers LayerGeometry)

            self._images = _image_provider()
            self.engine().addImageProvider(_ORBIT_PROVIDER, self._images)
            self._image_n = 0
            from arelis.ui.persona_face.orbit_state import OrbitState

            self.orbit_state = OrbitState(self)
            self.rootContext().setContextProperty("orbitState", self.orbit_state)
            logging.getLogger("arelis.avatar").info(
                "[avatar] quick surface: QQuickView, threaded loop, pipeline cache %s",
                pipeline_cache_path(),
            )
            self._frames = qq3d_avatar.frame_log()
            if self._frames is not None:
                qq3d_avatar.attach_frame_log(self, self, self._frames)
            self.setSource(QUrl.fromLocalFile(str(SURFACE_QML)))
            self._window = window
            window._quick_surface = self
            _install_accessible_factory()
            self.container = QWidget.createWindowContainer(self, window)
            self.container.setObjectName("QuickSurfaceContainer")
            self.container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            window.installEventFilter(self)
            self.container.setGeometry(window.rect())
            self.container.lower()
            self.container.show()
            self.mirror = WidgetMirror(self, window, self.container)
            self._cache_jobs: list = []
            self._suspended = False
            self._set_visible = gil_free_set_visible(self)
            self._first_frame = False
            self.frameSwapped.connect(self._on_first_frame, Qt.ConnectionType.QueuedConnection)

        def _on_first_frame(self) -> None:
            if self._first_frame:
                return
            self._first_frame = True
            self.frameSwapped.disconnect(self._on_first_frame)
            # Qt writes setPipelineCacheSaveFile only when the window is destroyed, which a
            # killed or tray-parked app never does: save once the first pipelines exist.
            QTimer.singleShot(5000, self.save_pipeline_cache)

        def save_pipeline_cache(self) -> None:
            """Write rhi().pipelineCacheData() from the render thread (where the QRhi lives)."""
            from PySide6.QtCore import QRunnable

            view = self

            class _Save(QRunnable):
                def run(self) -> None:
                    rhi = view.rhi()
                    if rhi is not None:
                        write_pipeline_cache(bytes(rhi.pipelineCacheData()))

            job = _Save()
            job.setAutoDelete(False)  # Python owns it; Qt deleting it under PySide crashes
            del self._cache_jobs[:-4]
            self._cache_jobs.append(job)
            self.scheduleRenderJob(job, QQuickWindow.RenderStage.NoStage)
            self.update()

        def suspend(self) -> None:
            """The host is going away (tray): stop her animations and the render loop."""
            if self._suspended:
                return
            self._suspended = True
            if self._first_frame:
                self.save_pipeline_cache()
            root = self.rootObject()
            if root is not None:
                root.setVisible(False)  # FrameAnimations run only while visible
            self._set_visible(False)

        def resume(self) -> None:
            if not self._suspended:
                return
            self._suspended = False
            root = self.rootObject()
            if root is not None:
                root.setVisible(True)
            self._set_visible(True)

        def parentWidget(self) -> QWidget:
            return self.container.parentWidget()

        def eventFilter(self, obj, event) -> bool:
            if obj is self._window and event.type() == QEvent.Type.Show:
                self.resume()
            if obj is self._window and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self.container.setGeometry(self._window.rect())
                self.container.lower()
                self.mirror.drop_tiles_outside()
                self.mirror.mark_all()
            return False

    return QuickSurfaceWindow


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
            save = getattr(self.surface, "save_pipeline_cache", None)
            if save is not None:
                QTimer.singleShot(2000, save)  # her pipelines are built by now

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
