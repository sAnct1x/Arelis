"""Her figure in Qt Quick 3D, in a QQuickWidget: the WebEngine host's replacement.

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
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

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
_FLUSH_MS = 1000


def engine() -> str:
    """'qq3d' or 'web' (the default until Quick 3D passes its gates)."""
    return "qq3d" if os.environ.get(ENGINE_ENV, "").strip().lower() == "qq3d" else "web"


def wanted(theme: str) -> bool:
    """Quick 3D hosts her only in the rooms it has landed in (Filament so far)."""
    return engine() == "qq3d" and (theme or "").strip().lower() == "filament"


def surface_format():
    """The default surface format her see-through hub needs, or None (web engine).

    A QQuickWidget stacked on top only shows the room under her when the
    window's GL surface has an alpha channel; without one her box is opaque
    black (box, OpenGL RHI). Call after the QApplication exists (the
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
        from PySide6.QtQuick3D import QQuick3D  # noqa: F401
        from PySide6.QtQuickWidgets import QQuickWidget  # noqa: F401
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
    """Her frames render on the GUI thread (QQuickWidget): keep it ahead of a model on every core.

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


class QQ3DAvatar(QWidget):
    """Hosts the Quick 3D scene. Call set_state and set_level; listen for failed."""

    failed = Signal(str)
    ready = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtQuickWidgets import QQuickWidget

        from arelis.ui.persona_face.panel import alog

        self._ready = False
        self._dead = False
        self._state = "idle"
        self._level = -1.0
        self.view = QQuickWidget(self)
        self.view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.view.setClearColor(QColor(Qt.GlobalColor.transparent))
        self.view.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        # She never takes a click: stop is the stop button or a spoken "stop".
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
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

        self.view.setSource(QUrl.fromLocalFile(str(ENTRY)))
        root = self.view.rootObject()
        if self.view.status() != QQuickWidget.Status.Ready or root is None:
            errs = "; ".join(e.toString() for e in self.view.errors()) or "no root"
            QTimer.singleShot(0, lambda: self._fail(f"scene error: {errs}"))
            return
        self.root = root
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

    def _start_frame_log(self, log: FrameLog) -> None:
        from PySide6.QtCore import QCoreApplication

        # QQuickWidget renders on the GUI thread: afterRendering is once per frame.
        self.view.quickWindow().afterRendering.connect(
            log.frame, Qt.ConnectionType.DirectConnection
        )
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
