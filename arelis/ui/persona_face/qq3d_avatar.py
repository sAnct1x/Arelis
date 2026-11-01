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


def unavailable_reason() -> str | None:
    """Why the Quick 3D avatar cannot start, or None when it may try."""
    if os.environ.get("ARELIS_WEB_AVATAR", "1").strip().lower() in _OFF:
        return "turned off by ARELIS_WEB_AVATAR"
    if not model_path().is_file():
        return f"no model at {model_path()}"
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

    def frame(self, *_args) -> None:
        if self._file is None:
            return
        now = self._clock()
        if self._last is not None:
            self._file.write(f"{now:.2f},{now - self._last:.3f}\n")
        self._last = now

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
        self._frames = frame_log()
        if self._frames is not None:
            self._start_frame_log(self._frames)
        model = model_path()
        alog("qq3d load", path=model, engine="qq3d")
        if model.name != LOOK_FILE:
            logging.getLogger("arelis.avatar").warning(
                "[avatar] no look (%s) in %s: plain model", LOOK_FILE, model.parent
            )
        check_clips()
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
            self._ready = True
            self._poll.stop()
            self._deadline.stop()
            from arelis.ui.persona_face.panel import alog

            alog("ready", engine="qq3d", clips=self.root.property("clip") or "-")
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
