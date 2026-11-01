"""Her figure in Qt Quick 3D, rendered off the GUI thread: the WebEngine host's replacement.

Same public API and signals as ``web_avatar.WebAvatar`` (set_state, set_level,
refit, refresh_theme_icons, is_ready, ready, failed), so PersonaPanel does not
change. The scene entry point is ``qq3d/Avatar.qml``; the model is not shipped:
it is the balsam output (``Ellah_anim.qml`` with its meshes, maps and
animations) read from the user's data folder, or ``ARELIS_AVATAR_QQ3D_DIR``.

Chosen with ``ARELIS_AVATAR_ENGINE=qq3d``; for now only in Filament.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from arelis.paths import user_data_dir
from arelis.ui.persona_face.web_avatar import STATE_MAP

QML_DIR = Path(__file__).resolve().parent / "qq3d"
ENTRY = QML_DIR / "Avatar.qml"
ENGINE_ENV = "ARELIS_AVATAR_ENGINE"
DIR_ENV = "ARELIS_AVATAR_QQ3D_DIR"
MODEL_FILE = "Ellah_anim.qml"
# tools/avatar_q3d_export.py writes the look (aether shaders on the same skeleton and clips).
LOOK_FILE = "Ellah_aether.qml"
_READY_TIMEOUT_MS = 30_000
_OFF = {"0", "false", "no", "off"}
FRAMETIME_ENV = "ARELIS_FRAMETIME_LOG"
# Her first frames log their beginFrame/sync/render/endFrame times (start-up cost).
_TIMED_FRAMES = 5
# Bump when the cache's meaning changes; a key mismatch makes the next start ignore the file.
_PIPELINE_CACHE_FORMAT = 1


def pipeline_cache_path() -> Path:
    """Her compiled pipelines (D3D11 bytecode, GL program binaries) across starts.

    Qt only writes its automatic cache when her window is destroyed, which a killed or
    crashed process never reaches, so every such start compiled every pipeline again
    (Atria: 14 s from ready to her first frame). This file is written by the render
    thread right after her first frame.
    """
    return user_data_dir() / "avatar" / "qq3d" / "pipeline.cache"


def pipeline_cache_key() -> str:
    from PySide6.QtCore import qVersion

    backend = os.environ.get("ARELIS_QT_RHI") or os.environ.get("QSG_RHI_BACKEND") or "default"
    return f"{_PIPELINE_CACHE_FORMAT}|qt{qVersion()}|{sys.platform}|{backend}"


def _use_pipeline_cache(view) -> None:
    """Point her window's QRhi at the cache file; a stale key (other Qt, backend) is ignored."""
    path = pipeline_cache_path()
    key = path.with_suffix(".key")
    cfg = view.graphicsConfiguration()
    cfg.setAutomaticPipelineCache(False)
    try:
        fresh = path.is_file() and key.read_text(encoding="utf-8") == pipeline_cache_key()
    except OSError:
        fresh = False
    if fresh:
        cfg.setPipelineCacheLoadFile(str(path))
    cfg.setPipelineCacheSaveFile(str(path))  # also asks QRhi to collect the data
    view.setGraphicsConfiguration(cfg)


_FLUSH_MS = 1000
# While her window says it is minimized, look again this often (the flag can be stale).
_MINIMIZED_RETRY_MS = 250
_KICK_EVENTS = (QEvent.Type.WindowStateChange, QEvent.Type.Show, QEvent.Type.Expose)


def engine() -> str:
    """'qq3d' or 'web' (the default until Quick 3D passes its gates)."""
    return "qq3d" if os.environ.get(ENGINE_ENV, "").strip().lower() == "qq3d" else "web"


def wanted(theme: str) -> bool:
    """Quick 3D hosts her only in the rooms it has landed in (Filament so far)."""
    return engine() == "qq3d" and (theme or "").strip().lower() == "filament"


def surface_format():
    """The default surface format her see-through hub needs, or None (web engine).

    Her render thread asks for the same format on its own window; the default
    keeps every other Quick surface in step with it. Call after the QApplication exists (the
    ideal format needs it) and before the first window.
    """
    if engine() != "qq3d":
        return None
    from PySide6.QtGui import QSurfaceFormat

    try:
        from PySide6.QtQuick3D import QQuick3D
    except Exception:
        return None  # unavailable_reason says why, once the panel starts
    fmt = QQuick3D.idealSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    return fmt


def model_dir() -> Path:
    override = os.environ.get(DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return user_data_dir() / "avatar" / "qq3d"


def model_path() -> Path:
    """Her look (LOOK_FILE, the aether port) when it is there, else the plain balsam model.

    The plain model has PrincipledMaterials lit by the stand-in lights; under the look's
    bloom and linear tonemap it reads as a white blown-out figure, so it is only a fallback.
    """
    look = model_dir() / LOOK_FILE
    return look if look.is_file() else model_dir() / MODEL_FILE


def clips_path() -> Path:
    """Her body clips: balsam writes them to animations/ beside the model."""
    return model_dir() / "animations"


def check_clips() -> bool:
    """True when the clips are there; else one ERROR line naming where they must go."""
    path = clips_path()
    if path.is_dir() and any(path.iterdir()):
        return True
    logging.getLogger("arelis.avatar").error("[avatar] clips missing at %s", path)
    return False


# Quoted file names: "meshes/x.mesh", "animations/x.qad", "aether_shaders/L3.vert",
# resolvedUrl("aether_scene/g3").
_REF = re.compile(r'"((?:file:|/|[A-Za-z]:|[\w.-]+/)[^"\n]*)"')


def missing_files(model: Path) -> list[Path]:
    """Every file the model QML names (meshes, maps, clips, shaders, geometry) that is missing.

    Relative names resolve against the model's folder, as QML does. An absolute path baked in on
    another machine (gate 1: /workspace/... on Windows) is reported as missing too.
    """
    if not model.is_file():
        return [model]
    out: list[Path] = []
    seen: set[str] = set()
    for ref in _REF.findall(model.read_text(encoding="utf-8", errors="replace")):
        if ref in seen or ref.startswith("qrc:"):
            continue
        seen.add(ref)
        if ref.startswith("file:"):
            from PySide6.QtCore import QUrl

            ref = QUrl(ref).toLocalFile()
        path = Path(ref) if Path(ref).is_absolute() else model.parent / ref
        # LayerGeometry and its morphs name a buffer prefix (".../g3"): its files are g3_*.bin.
        if path.suffix == "" and any(path.parent.glob(path.name + "_*.bin")):
            continue
        if not path.exists():
            out.append(path)
    return out


def model_error() -> str | None:
    """Why her model cannot draw (no model, files or clips), logged as an ERROR, or None."""
    log = logging.getLogger("arelis.avatar")
    model = model_path()
    if not model.is_file():
        searched = [model_dir() / LOOK_FILE, model_dir() / MODEL_FILE]
        log.error(
            "[avatar] qq3d model missing: searched %s (data folder %s, override %s)",
            ", ".join(str(p) for p in searched), user_data_dir(), DIR_ENV,
        )
        return f"no model at {searched[0]}"
    if not check_clips():
        return f"no clips at {clips_path()}"
    gone = missing_files(model)
    if gone:
        log.error(
            "[avatar] qq3d model %s: %d files it names are missing, first: %s",
            model, len(gone), ", ".join(str(p) for p in gone[:5]),
        )
        return f"model files missing ({len(gone)}), first {gone[0]}"
    return None


def unavailable_reason() -> str | None:
    """Why the Quick 3D avatar cannot start, or None when it may try."""
    if os.environ.get("ARELIS_WEB_AVATAR", "1").strip().lower() in _OFF:
        return "turned off by ARELIS_WEB_AVATAR"
    why = model_error()
    if why is not None:
        return why
    if not ENTRY.is_file():
        return "scene files missing"
    try:
        from PySide6.QtQuick import QQuickRenderControl  # noqa: F401
        from PySide6.QtQuick3D import QQuick3D  # noqa: F401
    except Exception as exc:
        return f"QtQuick3D unavailable: {exc}"
    return None


def theme_props() -> dict[str, object]:
    """The room as the scene sees it: tint, colours and backdrop."""
    from arelis.ui.persona_face.web_avatar import backdrop_color
    from arelis.ui.theme import color
    from arelis.ui.void_idle import aether_hue_shift

    return {
        "tint": float(aether_hue_shift()),
        "accent": color("accent"),
        "bg": color("bg0"),
        "text": color("text"),
        "backdrop": backdrop_color(),
    }


_STALL_MS = 400.0


def raise_gui_priority() -> None:
    """Keep the GUI thread (sync, blit, chat) ahead of a model on every core.

    llama-server runs one normal-priority thread per core while it generates; at the same
    priority the GUI thread waited its turn and frames went from 16 to 40+ ms. Above normal
    (Windows THREAD_PRIORITY_ABOVE_NORMAL) still yields to the system, and the orbit painter
    (filament_render) runs below normal so it never takes her slot.
    """
    from PySide6.QtCore import QThread

    QThread.currentThread().setPriority(QThread.Priority.HighPriority)


class StallWatch:
    """With the frame log on: a frame later than _STALL_MS logs what the GUI thread was running.

    A watcher thread reads the GUI thread's Python stack while the frame is late, so a gate
    log names the cause of a spike (a Python call, or Qt's own work under app.exec).
    """

    def __init__(self, log: FrameLog) -> None:
        import threading

        self._log = log
        self._gui = threading.get_ident()
        self._seen: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="frame-stall", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import sys
        import traceback

        while not self._stop.wait(0.1):
            last = self._log.last
            if last is None or last == self._seen:
                continue
            late = self._log.clock() - last
            if late < _STALL_MS:
                continue
            self._seen = last
            frame = sys._current_frames().get(self._gui)
            where = "".join(traceback.format_stack(frame, limit=8)) if frame else "?"
            logging.getLogger("arelis.avatar").warning(
                "[avatar] frame stall %.0f ms so far; GUI thread in:\n%s", late, where
            )

    def stop(self) -> None:
        self._stop.set()


class FrameLog:
    """``ARELIS_FRAMETIME_LOG``: one ``t_epoch_ms,frame_ms`` line per rendered frame.

    The gate script (gate_capture.file_frames) tails this file. The first frame
    has no previous one and writes no line. Buffered, flushed every second,
    closed with the host or at app exit.
    """

    def __init__(self, path: str, clock=None) -> None:
        import time

        self._clock = clock or (lambda: time.time() * 1000.0)
        self._file = open(path, "w", encoding="utf-8", buffering=1 << 16)
        self._last: float | None = None
        self.clock = self._clock

    def frame(self, *_args) -> None:
        if self._file is None:
            return
        now = self._clock()
        if self._last is not None:
            self._file.write(f"{now:.2f},{now - self._last:.3f}\n")
        self._last = now

    @property
    def last(self) -> float | None:
        return self._last

    def flush(self) -> None:
        if self._file is not None:
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def frame_log() -> FrameLog | None:
    path = os.environ.get(FRAMETIME_ENV, "").strip()
    return FrameLog(path) if path else None


# QQuickRenderControl's frame calls by their C++ symbols. PySide keeps the GIL through a wrapped
# call, so endFrame (which waits for the GPU) would stall every Python slot on the GUI thread for
# the whole frame; a ctypes call drops the GIL for its duration.
_SYMBOLS = {
    "render": ("_ZN19QQuickRenderControl6renderEv", "?render@QQuickRenderControl@@QEAAXXZ"),
    "endFrame": ("_ZN19QQuickRenderControl8endFrameEv", "?endFrame@QQuickRenderControl@@QEAAXXZ"),
}
_LIBS = ("libQt6Quick.so.6", "Qt6Quick.dll", "QtQuick.framework/QtQuick")


def _quick_library():
    import ctypes

    from PySide6.QtCore import QLibraryInfo

    dirs = [""] + [QLibraryInfo.path(p) for p in (QLibraryInfo.LibraryPath.LibrariesPath,
                                                  QLibraryInfo.LibraryPath.BinariesPath)]
    import PySide6

    dirs.append(os.path.dirname(PySide6.__file__))
    for d in dirs:
        for name in _LIBS:
            try:
                return ctypes.CDLL(os.path.join(d, name) if d else name)
            except OSError:
                continue
    return None


def gil_free_calls(control) -> dict[str, object]:
    """``{"render": f, "endFrame": f}`` calling the control without the GIL; a missing symbol
    falls back to the PySide call (correct, but holding the GIL), logged once."""
    import ctypes

    import shiboken6

    lib = _quick_library()
    this = ctypes.c_void_p(shiboken6.getCppPointer(control)[0])
    out: dict[str, object] = {}
    for name, symbols in _SYMBOLS.items():
        fn = None
        for sym in symbols:
            fn = getattr(lib, sym, None) if lib is not None else None
            if fn is not None:
                break
        if fn is None:
            logging.getLogger("arelis.avatar").warning(
                "[avatar] qq3d %s keeps the GIL (no %s in Qt Quick)", name, symbols
            )
            out[name] = getattr(control, name)
            continue
        fn.restype = None
        fn.argtypes = [ctypes.c_void_p]
        out[name] = lambda fn=fn: fn(this)
    return out


_LIVE: set = set()  # running render threads, kept until dispose so GC never frees one mid-frame


class _RenderThread(QThread):
    """Her frames: sync, render and read back on this thread, never on the GUI thread.

    The GUI thread asks for a frame only while this thread is idle, so it never waits on
    the GPU: it blocks just for ``QQuickRenderControl.sync`` (copying the scene state, as
    Qt's threaded render loop does) and then blits the last finished image. Waits use
    ``threading`` conditions, which drop the GIL.
    """

    frame_ready = Signal()  # emitted on the render thread; queued to the GUI thread

    def __init__(self, control, window) -> None:
        import threading

        super().__init__()
        self.setObjectName("qq3d-render")
        self._control = control
        self._window = window
        self._cv = threading.Condition()
        self._job: tuple[int, int] | None = None  # pixel size of the next frame
        self._synced = False
        self._stop = False
        self.busy = False
        self.image = None
        self.error: str | None = None
        self._tex = self._rt = self._rp = None
        self._calls = gil_free_calls(control)
        self._ctx = None  # OpenGL only: the context, owned by this thread while it runs
        self._size: tuple[int, int] | None = None
        self._timed = 0  # frames whose step times were logged (the first _TIMED_FRAMES)

    # ---- GUI thread ----

    def initialize(self) -> str | None:
        """Create her QRhi here (an OpenGL fallback surface must come from the GUI thread),
        then hand its context to the render thread. Returns why it failed, or None."""
        if not self._control.initialize():
            return "Quick 3D render control did not initialise"
        from PySide6.QtGui import QOpenGLContext, QRhi

        rhi = self._control.rhi()
        ctx = QOpenGLContext.currentContext()
        gl = rhi is not None and rhi.backend() == QRhi.Implementation.OpenGLES2
        if gl and ctx is not None:  # an OpenGL context is current on one thread only
            ctx.doneCurrent()
            ctx.moveToThread(self)
            self._ctx = ctx
        return None

    def frame(self, size: tuple[int, int]) -> bool:
        """Sync one frame (GUI blocked only for the sync); False when a frame is in flight."""
        with self._cv:
            if self.busy or self._stop or self.error:
                return False
            self.busy = True
            self._synced = False
            self._job = size
            self._cv.notify_all()
            while not self._synced and not self._stop and self.error is None:
                self._cv.wait(0.5)
            return True

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        self.wait(5000)

    def dispose(self, *_args) -> None:
        """Stop the thread, then free the scene, its window and the control, in that order."""
        import shiboken6

        if not shiboken6.isValid(self):  # Qt already freed it (a host that failed to start)
            _LIVE.discard(self)
            return
        if self.isRunning():
            self.stop()
        _LIVE.discard(self)
        for name in ("root", "_window", "engine", "_control"):
            obj = getattr(self, name, None)
            if obj is not None:
                obj.deleteLater()
                setattr(self, name, None)

    # ---- render thread ----

    def _target(self, size: tuple[int, int]) -> None:
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QRhiTexture
        from PySide6.QtQuick import QQuickRenderTarget

        if size == self._size:
            return
        for res in (self._rt, self._rp, self._tex):
            if res is not None:
                res.destroy()
        rhi = self._control.rhi()
        flags = QRhiTexture.Flag.RenderTarget | QRhiTexture.Flag.UsedAsTransferSource
        self._tex = rhi.newTexture(QRhiTexture.Format.RGBA8, QSize(*size), 1, flags)
        self._tex.create()
        from PySide6.QtGui import QRhiColorAttachment, QRhiTextureRenderTargetDescription

        desc = QRhiTextureRenderTargetDescription(QRhiColorAttachment(self._tex))
        self._rt = rhi.newTextureRenderTarget(desc)
        self._rp = self._rt.newCompatibleRenderPassDescriptor()
        self._rt.setRenderPassDescriptor(self._rp)
        self._rt.create()
        self._window.setRenderTarget(QQuickRenderTarget.fromRhiRenderTarget(self._rt))
        self._size = size

    def run(self) -> None:
        try:
            self._loop()
        except Exception as exc:  # pragma: no cover - a driver fault
            with self._cv:
                self.error = f"render thread: {exc}"
                self.busy = False
                self._cv.notify_all()
        finally:
            self._release()

    def _loop(self) -> None:
        from PySide6.QtGui import QImage, QRhiReadbackDescription, QRhiReadbackResult

        while True:
            with self._cv:
                while self._job is None and not self._stop:
                    self._cv.wait()
                if self._stop:
                    break
                size, self._job = self._job, None
            t0 = time.perf_counter()
            self._target(size)
            self._control.beginFrame()
            t1 = time.perf_counter()
            self._control.sync()
            t2 = time.perf_counter()
            with self._cv:
                self._synced = True  # the GUI thread may go on; the GPU work is ours
                self._cv.notify_all()
            self._calls["render"]()
            t3 = time.perf_counter()
            result = QRhiReadbackResult()
            batch = self._control.rhi().nextResourceUpdateBatch()
            batch.readBackTexture(QRhiReadbackDescription(self._tex), result)
            self._control.commandBuffer().resourceUpdate(batch)
            self._calls["endFrame"]()  # an offscreen frame: the readback is complete here
            if self._timed < _TIMED_FRAMES:
                self._timed += 1
                if self._timed == 1:
                    self._save_pipeline_cache()
                t4 = time.perf_counter()
                logging.getLogger("arelis.avatar").info(
                    "[avatar] qq3d frame %d begin=%.1fms sync=%.1fms render=%.1fms end=%.1fms",
                    self._timed, (t1 - t0) * 1e3, (t2 - t1) * 1e3, (t3 - t2) * 1e3,
                    (t4 - t3) * 1e3,
                )
            data = bytes(result.data)
            w, h = result.pixelSize.width(), result.pixelSize.height()
            img = QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888_Premultiplied).copy()
            if self._control.rhi().isYUpInFramebuffer():
                img = img.flipped(Qt.Orientation.Vertical)
            with self._cv:
                self.image = img
                self.busy = False
            self.frame_ready.emit()

    def _save_pipeline_cache(self) -> None:
        try:
            data = bytes(self._control.rhi().pipelineCacheData())
            if not data:
                return
            path = pipeline_cache_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            path.with_suffix(".key").write_text(pipeline_cache_key(), encoding="utf-8")
        except (OSError, RuntimeError, AttributeError):
            logging.getLogger("arelis.avatar").debug("pipeline cache not saved", exc_info=True)

    def _release(self) -> None:
        if self._timed:
            self._save_pipeline_cache()  # pipelines first built after frame 1
        for res in (self._rt, self._rp, self._tex):
            if res is not None:
                res.destroy()
        self._control.invalidate()
        if self._ctx is not None:  # back to the GUI thread, where the control is destroyed
            from PySide6.QtCore import QCoreApplication

            self._ctx.doneCurrent()
            self._ctx.moveToThread(QCoreApplication.instance().thread())


class QQ3DAvatar(QWidget):
    """Hosts the Quick 3D scene. Call set_state and set_level; listen for failed.

    She stays an ordinary child widget in the main window (no native window, no airspace):
    tiles and chat paint over her, and she moves, resizes and hides with the window. The
    scene renders on its own thread through QQuickRenderControl; this widget only paints
    the latest finished frame.
    """

    failed = Signal(str)
    ready = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtQml import QQmlComponent, QQmlEngine
        from PySide6.QtQuick import QQuickRenderControl, QQuickWindow

        from arelis.ui.persona_face.panel import alog

        self._ready = False
        self._dead = False
        self._state = "idle"
        self._level = -1.0
        self._image = None
        # She never takes a click: stop is the stop button or a spoken "stop".
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._pending = False
        self._watched = None
        self._kick = QTimer(self)
        self._kick.setSingleShot(True)
        self._kick.setInterval(0)
        self._kick.timeout.connect(self._next_frame)
        # Her window is never shown, so a platform without RHI windows (offscreen) would pick
        # the software adaptation, which has no QRhi to render Quick 3D into.
        software = QQuickWindow.sceneGraphBackend() in ("", "software")
        if software and not os.environ.get("QT_QUICK_BACKEND"):
            QQuickWindow.setSceneGraphBackend("rhi")
        self.control = QQuickRenderControl()  # owned by _render: freed after its thread stops
        self.view = QQuickWindow(self.control)
        self.view.setColor(QColor(Qt.GlobalColor.transparent))
        from PySide6.QtQuick3D import QQuick3D

        fmt = QQuick3D.idealSurfaceFormat()  # OpenGL: a core 3.x context, not the 2.1 default
        fmt.setAlphaBufferSize(8)
        self.view.setFormat(fmt)
        _use_pipeline_cache(self.view)
        self._render = _RenderThread(self.control, self.view)
        render = self._render
        _LIVE.add(render)
        self.destroyed.connect(lambda *_: render.dispose())
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.instance().aboutToQuit.connect(lambda: render.dispose())
        self._render.frame_ready.connect(self._on_frame, Qt.ConnectionType.QueuedConnection)
        self.control.prepareThread(self._render)
        why = self._render.initialize()
        if why is not None:
            QTimer.singleShot(0, lambda: self._fail(why))
            return
        self._render.start(QThread.Priority.HighPriority)
        self._watch_window()
        self.control.renderRequested.connect(self._request)
        self.control.sceneChanged.connect(self._request)
        raise_gui_priority()
        self._frames = frame_log()
        if self._frames is not None:
            self._start_frame_log(self._frames)
        model = model_path()
        alog("qq3d load", path=model, engine="qq3d")
        if model.name != LOOK_FILE:
            logging.getLogger("arelis.avatar").warning(
                "[avatar] no look (%s) in %s: plain model", LOOK_FILE, model.parent
            )
        # The look (Ellah_aether.qml) imports Arelis.PersonaQ3D for its LayerGeometry; importing the
        # module registers that QML type.
        import arelis.ui.persona_q3d.geometry  # noqa: F401

        self.engine = self._render.engine = QQmlEngine()
        component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(ENTRY)))
        root = component.create() if component.isReady() else None
        if root is None:
            errs = "; ".join(e.toString() for e in component.errors()) or "no root"
            QTimer.singleShot(0, lambda: self._fail(f"scene error: {errs}"))
            return
        self._component = component
        root.setParentItem(self.view.contentItem())
        self.root = self._render.root = root
        self._fit()
        self._apply_theme()
        root.setProperty("avatarState", self._state)
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._on_status)
        self._poll.start()
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(lambda: self._fail("scene did not report ready"))
        self._deadline.start(_READY_TIMEOUT_MS)
        root.setProperty("modelSource", QUrl.fromLocalFile(str(model)))
        self._request()

    # ---- frames ----

    def _fit(self) -> None:
        root = getattr(self, "root", None)
        w, h = max(1, self.width()), max(1, self.height())
        self.view.resize(w, h)  # SizeRootObjectToView
        if root is not None:
            root.setWidth(w)
            root.setHeight(h)

    def _pixel_size(self) -> tuple[int, int]:
        dpr = self.devicePixelRatioF()
        return max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr))

    def _request(self, *_args) -> None:
        self._pending = True
        if not self._kick.isActive() or self._kick.remainingTime() > 0:
            self._kick.start(0)

    def _watch_window(self) -> None:
        """Re-kick on her window's state changes and shows (the child's own showEvent does
        not come when a minimized window is restored at the same size)."""
        top = self.window()
        if top is self._watched:
            return
        if self._watched is not None:
            self._watched.removeEventFilter(self)
        self._watched = top
        if top is not None and top is not self:
            top.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._watched and event.type() in _KICK_EVENTS:
            self._request()
        return False

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ParentChange:
            self._watch_window()
        return super().event(event)

    def _next_frame(self) -> None:
        if not self._pending or self._dead or getattr(self, "root", None) is None:
            return
        if not self.isVisible():
            return  # still pending: showEvent (hers or the window's) asks again
        top = self.window()
        if top is not None and top.isMinimized():
            # isMinimized() can be stale (a window that starts minimized, or restored without
            # a resize, on Windows), so this only slows her down; it never parks her for good.
            self._kick.start(_MINIMIZED_RETRY_MS)
            return
        self.control.polishItems()
        if self._render.frame(self._pixel_size()):
            self._pending = False
        elif self._render.error:
            self._fail(self._render.error)
        # else a frame is in flight: _on_frame asks again when it lands

    def _on_frame(self) -> None:
        self._image = self._render.image
        self.update()
        if self._pending:
            self._kick.start(0)

    def paintEvent(self, _event) -> None:
        img = self._image
        if img is None:
            return
        from PySide6.QtGui import QPainter

        img.setDevicePixelRatio(img.width() / max(1, self.width()))
        painter = QPainter(self)
        painter.drawImage(0, 0, img)
        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()
        self._request()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._watch_window()
        self._request()

    def _start_frame_log(self, log: FrameLog) -> None:
        from PySide6.QtCore import QCoreApplication

        # afterRendering is once per frame, on the render thread.
        self.view.afterRendering.connect(log.frame, Qt.ConnectionType.DirectConnection)
        flush = QTimer(self)
        flush.setInterval(_FLUSH_MS)
        flush.timeout.connect(log.flush)
        flush.start()
        watch = StallWatch(log)
        self.destroyed.connect(watch.stop)
        self.destroyed.connect(log.close)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(log.close)

    def is_ready(self) -> bool:
        return self._ready and not self._dead

    def set_state(self, panel_state: str) -> None:
        name = STATE_MAP.get(panel_state, "idle")
        if name != self._state:
            self._state = name
            self._set("avatarState", name)
            self._set("speaking", name == "speaking")

    def set_level(self, level: float | None) -> None:
        v = 0.0 if level is None else max(0.0, min(1.0, float(level)))
        if abs(v - self._level) >= 0.01:
            self._level = v
            self._set("level", v)

    def refit(self) -> None:
        """The layout settled: Quick 3D follows the size; the scene redraws."""
        if not self._dead and getattr(self, "root", None) is not None:
            self.root.metaObject().invokeMethod(self.root, "refit")

    def refresh_theme_icons(self) -> None:
        """Theme-change hook (settings_host): retint her to the new room."""
        from arelis.ui.persona_face.panel import alog
        from arelis.ui.theme_tokens import active_theme

        props = self._apply_theme()
        alog("theme", name=active_theme(), tint=int(props["tint"]))

    def _apply_theme(self) -> dict[str, object]:
        props = theme_props()
        for key, value in props.items():
            self._set(key, value)
        return props

    def _set(self, key: str, value: object) -> None:
        root = getattr(self, "root", None)
        if root is not None and not self._dead:
            root.setProperty(key, value)

    def _on_status(self, *_args) -> None:
        if self._dead or self._ready:
            return
        status = self.root.property("sceneStatus")
        if status == "error":
            self._fail(f"scene error: {self.root.property('sceneError')}")
        elif status == "ready":
            from arelis.ui.persona_q3d import geometry

            clips = int(self.root.property("clipCount") or 0)
            if geometry.MISSING:
                self._fail(f"geometry missing: {geometry.MISSING[0]}")
                return
            if clips == 0:
                logging.getLogger("arelis.avatar").error(
                    "[avatar] qq3d model %s loaded with no clips (Timelines); clips folder %s",
                    model_path(), clips_path(),
                )
                self._fail("model has no clips")
                return
            self._ready = True
            self._poll.stop()
            self._deadline.stop()
            from arelis.ui.persona_face.panel import alog

            alog("ready", engine="qq3d", clips=clips)
            self.ready.emit()

    def _fail(self, reason: str) -> None:
        if self._dead:
            return
        self._dead = True
        for t in ("_poll", "_deadline"):
            timer = getattr(self, t, None)
            if timer is not None:
                timer.stop()
        from arelis.ui.persona_face.panel import LOG

        LOG.warning("[avatar] failed reason=%r", reason)
        self.failed.emit(reason)
