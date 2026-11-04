"""ARELIS_SURFACE=quick: one on-screen Qt Quick surface under the whole window (slice 1).

The default ("widget") keeps QQ3DAvatar: an offscreen QQuickRenderControl texture read back
to a QImage every frame, and the Filament orbit blitted by the window's paintEvent. Under
the flag the window's bottom layer is a single QQuickWidget (QuickSurface) that draws the
void, the Filament orbit (slice 2: ring, strands, dust and hub threads, and in idle the
v11b orbit tree, drawn by QuickOrbit.qml's shaders from OrbitState; the beads, stems and
tethers still a worker-painted image layer over them), and her figure at her panel's rect.
QuickSurfaceAvatar is QQ3DAvatar (her scene on its own render thread, read back) whose frames
the surface draws in its avatarSlot instead of the widget painting them: a QQuickWidget
renders on the GUI thread, so her load (meshes, shaders, pipelines) must not happen in it.

QQuickWidget, not createWindowContainer: a container is a native child window, and on
Windows a native child always paints above its sibling widgets (airspace), so the tiles and
chrome could not sit over it. QQuickWidget renders into a texture the widget backing store
composites in z-order, so lower() really puts it under every other child.
"""

from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QRectF, Qt, QTimer, QUrl, Signal
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


_TIMED_SURFACE_FRAMES = 8
READBACK_ENV = "ARELIS_QQ3D_READBACK"  # "1": hand her frames over as images (A/B, a bad driver)


def _figure_item_class():
    from PySide6.QtQuick import QQuickItem, QSGSimpleTextureNode, QSGTexture

    from arelis.ui.persona_face import shared_frame

    class FigureItem(QQuickItem):
        """Her shared frame in avatarSlot: the texture her thread drew, never copied."""

        def __init__(self, slot, kind: str, on_shown, on_fail) -> None:
            super().__init__(slot)
            self.setFlag(QQuickItem.Flag.ItemHasContents, True)
            self._kind, self._on_shown, self._on_fail = kind, on_shown, on_fail
            self._consumer = None
            self.frame = None
            self._drawn = None
            self._fit()
            slot.widthChanged.connect(self._fit)
            slot.heightChanged.connect(self._fit)

        def _fit(self) -> None:
            slot = self.parentItem()
            if slot is not None:
                self.setSize(slot.size())
                self.update()

        def show(self, frame) -> None:
            self.frame = frame
            self.setVisible(frame is not None)
            self.update()

        def updatePaintNode(self, node, _data):  # the surface's render: the GUI thread
            frame = self.frame
            if frame is None:
                return None
            try:
                if self._consumer is None:
                    win = self.window()
                    self._consumer = shared_frame.Consumer(self._kind, win)
                    # Free her textures while the surface's QRhi still exists.
                    direct = Qt.ConnectionType.DirectConnection
                    win.sceneGraphInvalidated.connect(self.close, direct)
                    QCoreApplication.instance().aboutToQuit.connect(self.close, direct)
                texture = self._consumer.texture(frame)
            except Exception as exc:
                self.frame = None
                reason = f"{type(exc).__name__}: {exc}"
                QTimer.singleShot(0, self, lambda: self._on_fail(reason))
                return None
            if node is None:
                node = QSGSimpleTextureNode()
                node.setFiltering(QSGTexture.Filtering.Linear)
            node.setTexture(texture)
            node.setRect(self.boundingRect())
            flag = QSGSimpleTextureNode.TextureCoordinatesTransformFlag
            node.setTextureCoordinatesTransform(
                flag.MirrorVertically if frame.y_up else flag.NoTransform
            )
            self._consumer.forget_before(frame.generation)
            before, self._drawn = self._drawn, frame
            self._on_shown(frame, before)
            return node

        def close(self, *_args) -> None:
            self.frame = None
            if self._consumer is not None:
                self._consumer.close()
                self._consumer = None

    return FigureItem


def _quick_widget_class():
    from PySide6.QtQuickWidgets import QQuickWidget

    class QuickSurface(QQuickWidget):
        """The window's single full-window Quick layer, kept lowest and window-sized."""

        shaders_ready = Signal(str)  # from orbit_shaders' worker; queued to the GUI thread

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

            self._figure_item = None
            self._images = _image_provider()
            self.engine().addImageProvider(_ORBIT_PROVIDER, self._images)
            self._image_n = 0
            from arelis.ui.persona_face.orbit_state import OrbitState

            self.orbit_state = OrbitState(self)
            self.rootContext().setContextProperty("orbitState", self.orbit_state)
            # No pipeline cache here: a QQuickWidget renders with its top-level window's
            # backing-store QRhi, which Qt creates without EnablePipelineCacheDataSave. Her
            # figure is not rendered here for that reason (QuickSurfaceAvatar): only the void,
            # the orbit and the images are, whose few pipelines build quickly.
            logging.getLogger("arelis.avatar").info(
                "[avatar] quick surface: no pipeline cache (QQuickWidget uses the window's QRhi)"
            )
            # ARELIS_FRAMETIME_LOG: the same frames.csv as the readback path, one line per
            # surface frame (her, the orbit image and the backdrop render together here).
            self._frames = qq3d_avatar.frame_log()
            if self._frames is not None:
                qq3d_avatar.attach_frame_log(self, self.quickWindow(), self._frames)
            self.setSource(QUrl.fromLocalFile(str(SURFACE_QML)))
            from arelis.ui.persona_face import orbit_shaders

            self._timed_frames = 0
            self._frame_t0 = 0.0
            win = self.quickWindow()
            win.beforeSynchronizing.connect(self._frame_began, Qt.ConnectionType.DirectConnection)
            win.afterRendering.connect(self._frame_done, Qt.ConnectionType.DirectConnection)
            self.shaders_ready.connect(self.set_shaders, Qt.ConnectionType.QueuedConnection)
            self.set_shaders(orbit_shaders.shader_root(self._emit_shaders))
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

        def _frame_began(self) -> None:
            self._frame_t0 = time.perf_counter()

        def _frame_done(self) -> None:
            """Log the first surface frames: these run on the GUI thread (QQuickWidget)."""
            if self._timed_frames >= _TIMED_SURFACE_FRAMES or not self._frame_t0:
                return
            self._timed_frames += 1
            logging.getLogger("arelis.avatar").info(
                "[avatar] quick surface frame %d %dx%d sync+render=%.1fms shaders=%s",
                self._timed_frames, self.width(), self.height(),
                (time.perf_counter() - self._frame_t0) * 1e3, self.orbit_shaders or "building",
            )

        def _emit_shaders(self, folder: str) -> None:  # the worker thread
            import shiboken6

            try:
                if shiboken6.isValid(self):
                    self.shaders_ready.emit(folder)
            except RuntimeError:  # the surface went between the check and the emit
                pass

        def set_shaders(self, folder: str) -> None:
            """Where the orbit's .qsb files are; "" hides the orbit until they are built."""
            self.orbit_shaders = folder
            root = self.rootObject()
            if root is not None:
                root.setProperty("orbitShaders", folder)

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

        def set_figure(self, image: QImage | None) -> None:
            """Her latest frame from her render thread, drawn in avatarSlot; None clears it."""
            if self._figure_item is not None:
                self._figure_item.show(None)
            self._set_image("figure", "figureSource", image)

        def figure_rhi(self):
            """The QRhi her shared frames must open on (None before the first render)."""
            return self.quickWindow().rhi()

        def set_figure_frame(self, frame, kind: str, on_shown, on_fail) -> None:
            """Her shared frame (shared_frame.Frame): drawn from her texture, no image."""
            if self._figure_item is None:
                slot = self.slot()
                if slot is None:
                    return
                self._figure_item = _figure_item_class()(slot, kind, on_shown, on_fail)
            self._set_image("figure", "figureSource", None)
            self._figure_item.show(frame)

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


class QuickSurfaceAvatar(QQ3DAvatar):
    """Her figure for the Quick surface: rendered on her own thread, drawn by the surface.

    She used to be created inside the surface itself (a QQuickWidget), and a QQuickWidget
    renders on the GUI thread with the window's QRhi, which has no pipeline cache. Her first
    frames build every material's shaders and pipelines (D3DCompile on Windows) and upload
    78 MB of meshes there, so the GUI thread stalled about 10 s twice and the tray menu could
    not open. Now QQ3DAvatar's render thread (its own QQuickRenderControl and QRhi, with the
    pipeline cache saved across starts) does all of that, and the GUI thread only polishes
    and syncs. Each finished frame goes to the surface's avatarSlot, so she still sits in the
    surface's z-order, under the tiles and chrome: as the texture her thread drew where the
    two QRhis can share it (shared_frame.py: D3D11, OpenGL), else as a read-back image.

    This widget paints nothing: it holds her place in the panel layout, and her slot on the
    surface follows its rect (mapped to the window) and its visibility.
    """

    OWN_FRAME_LOG = False  # the surface logs the frames she is shown in: frames.csv's one writer
    # She is drawn by the surface. An update() here at her frame rate repainted this empty
    # widget and, as it is not opaque, the window under it: a second window composite per
    # frame on top of the surface's own.
    PAINTS_HER = False

    def __init__(self, parent: QWidget | None = None) -> None:
        self.surface = None
        self._slot = None
        self._watched_up: list[QWidget] = []
        self._attaching = False
        self._shown_from: int | None = None  # the first frame() call that has her posed
        self._share_kind: str | None = None  # "d3d11"/"gl" once frames are shared, "" if not
        self._share_waiting = False
        # QQ3DAvatar returns early (before setting root) when her render control cannot start
        # (no GPU context); _drop, _place and the tests read root on that path too.
        self.root = None
        super().__init__(parent)
        # With self as the context, Qt drops the call when this widget is gone first. A bare
        # bound method still ran on a host deleted in the same turn (a theme switch, a test
        # window torn down) and raised "QuickSurfaceAvatar already deleted" from the event loop.
        QTimer.singleShot(0, self, self._attach)

    def _scene_compiled(self, *args) -> None:
        had = getattr(self, "root", None)
        super()._scene_compiled(*args)
        root = getattr(self, "root", None)
        # Her scene compiles asynchronously, so root first exists here, not after __init__.
        if had is None and root is not None and not self._dead:
            root.chestChanged.connect(self._on_chest)

    # ---- attach and place ----

    def _attach(self) -> None:
        if self._dead or self.surface is not None or self._attaching or not self.isVisible():
            return
        top = self.window()
        if top is self:
            return
        # Building the surface on a shown window shows it, which re-enters this through
        # showEvent before surface_for returns: one attach, one surface.
        self._attaching = True
        try:
            surface = surface_for(top)
        except Exception as exc:
            self._fail(f"quick surface failed: {exc}")
            return
        finally:
            self._attaching = False
        slot = surface.slot()
        if slot is None:
            errs = "; ".join(e.toString() for e in surface.errors()) or "no surface root"
            self._fail(f"surface error: {errs}")
            return
        self.surface, self._slot = surface, slot
        self._watch_ancestors()
        self._place()
        self._try_share()
        if not self._shown():
            surface.set_loading(True)
        if self._image is not None:
            self._show_figure(self._image)

    def _watch_ancestors(self) -> None:
        for w in self._watched_up:
            w.removeEventFilter(self)
        self._watched_up = []
        w = self.parentWidget()
        while w is not None:
            w.installEventFilter(self)
            self._watched_up.append(w)
            if w.isWindow():
                break
            w = w.parentWidget()

    def eventFilter(self, obj, event) -> bool:
        if event.type() in _TRACKED:
            self._place()
        return super().eventFilter(obj, event)

    def _place(self) -> None:
        slot = self._slot
        if slot is None or self.surface is None:
            return
        top = self.surface.parentWidget()
        pos = self.mapTo(top, QPointF(0, 0)) if top is not None else QPointF(0, 0)
        slot.setX(pos.x())
        slot.setY(pos.y())
        slot.setWidth(max(1, self.width()))
        slot.setHeight(max(1, self.height()))
        slot.setVisible(self.isVisible() and not self._dead)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._place()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.surface is None:
            self._attach()
        self._place()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._place()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ParentChange and self.surface is not None:
            self._watch_ancestors()
            self._place()
        return super().event(event)

    def closeEvent(self, event) -> None:
        self._drop()
        super().closeEvent(event)

    def _drop(self) -> None:
        # A host swapped out mid-load (a theme switch): its poll and deadline stop, and the
        # window's loading veil goes, or it breathes on forever over the next host. Her scene
        # itself is freed with her render thread (QQ3DAvatar's dispose on destroyed).
        for t in ("_poll", "_deadline", "_kick"):
            timer = getattr(self, t, None)
            if timer is not None:
                timer.stop()
        if self.surface is not None:
            if not self._shown():
                self.surface.set_loading(False)
            self._show_figure(None)
        if self._slot is not None:
            self._slot.setVisible(False)
        for w in self._watched_up:
            w.removeEventFilter(self)
        self._watched_up = []
        root, self.root = getattr(self, "root", None), None
        if root is not None:
            try:
                root.chestChanged.disconnect(self._on_chest)
            except (RuntimeError, TypeError):
                pass

    def deleteLater(self) -> None:  # panel swaps hosts with hide() + deleteLater()
        self._drop()
        super().deleteLater()

    # ---- frames: the render thread's image, drawn by the surface ----

    def _show_figure(self, image) -> None:
        """Hand her frame (or None) to the surface; a surface without set_figure is skipped."""
        show = getattr(self.surface, "set_figure", None)
        if show is not None:
            show(image)

    def _try_share(self, *_args) -> None:
        """Hand frames over as textures once the surface has its QRhi (its first render)."""
        from arelis.ui.persona_face import shared_frame

        surface, render = self.surface, getattr(self, "_render", None)
        if self._dead or surface is None or render is None or self._share_kind is not None:
            return
        rhi_of = getattr(surface, "figure_rhi", None)
        if rhi_of is None:
            return
        rhi = rhi_of()
        if rhi is None:
            if not self._share_waiting:
                self._share_waiting = True
                surface.quickWindow().sceneGraphInitialized.connect(
                    self._try_share, Qt.ConnectionType.QueuedConnection
                )
            return
        her = self.control.rhi()
        kind = None if os.environ.get(READBACK_ENV) == "1" else shared_frame.kind_for(her, rhi)
        self._share_kind = kind or ""
        log = logging.getLogger("arelis.avatar")
        if not kind:
            log.info(
                "[avatar] qq3d frames: readback (her %s, surface %s%s)",
                her.backendName() if her else "-", rhi.backendName(),
                ", forced" if os.environ.get(READBACK_ENV) == "1" else "",
            )
            return
        render.share(kind)

    def _shared_failed(self, reason: str) -> None:
        render = getattr(self, "_render", None)
        if render is not None:
            render.unshare(reason)
        if self.surface is not None:
            self._show_figure(self._image)
        self._request()

    def _shown(self) -> bool:
        return self._shown_from is not None and self._image_seq >= self._shown_from

    def _on_frame(self) -> None:
        super()._on_frame()
        frame = self._render.shared
        if self.surface is not None and not self._dead:
            show = getattr(self.surface, "set_figure_frame", None)
            if frame is not None and self._share_kind and show is not None:
                show(frame, self._share_kind, self._render.shown, self._shared_failed)
            else:
                self._show_figure(self._image)
            if self._shown():
                self.surface.set_loading(False)
        if self._ready and not self._shown():
            # A still scene asks for no frame after ready, so ask here until a posed frame
            # has landed; otherwise the breathing state could stay over her for good.
            self._request()

    def paintEvent(self, _event) -> None:
        pass  # the surface draws her

    def _on_status(self, *args) -> None:
        super()._on_status(*args)
        if self._ready and self._shown_from is None:
            # Ready means posed, but the frame in flight may predate that, and her first posed
            # frame is the one that builds her pipelines: the breathing state stays until a
            # frame begun after ready lands, so she never shows as an empty slot.
            self._shown_from = self._render._started + 1
            self._request()

    def _on_chest(self) -> None:
        """Her chest bone, mapped to the window: where the Filament chat strand starts."""
        root, slot = getattr(self, "root", None), self._slot
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
            if self._slot is not None:
                self._slot.setVisible(False)
            if self.surface is not None:
                self.surface.set_loading(False)
                self._show_figure(None)
        super()._fail(reason)
