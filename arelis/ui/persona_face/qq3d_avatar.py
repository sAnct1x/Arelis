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
_READY_TIMEOUT_MS = 30_000
_OFF = {"0", "false", "no", "off"}


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
    return model_dir() / MODEL_FILE


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
    """The room as the scene sees it: tint, colours, backdrop and hub mode."""
    from arelis.ui.persona_face.web_avatar import backdrop_color
    from arelis.ui.persona_stage import region_mode
    from arelis.ui.theme import color
    from arelis.ui.theme_tokens import active_theme
    from arelis.ui.void_idle import aether_hue_shift

    return {
        "tint": float(aether_hue_shift()),
        "accent": color("accent"),
        "bg": color("bg0"),
        "text": color("text"),
        "backdrop": backdrop_color(),
        "hub": region_mode(active_theme()) == "hub",
    }


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
        model = model_path()
        alog("qq3d load", path=model.parent, engine="qq3d")
        check_clips()
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
