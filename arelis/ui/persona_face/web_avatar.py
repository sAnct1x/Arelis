"""Optional three.js avatar in a QWebEngineView. The painted face stays the fallback.

The scene ships in ``web/`` next to this file and loads over file:// only. The
model is not shipped: it is read from the user's data folder (or
``ARELIS_AVATAR_GLB``). Any failure (no QtWebEngine, no model, no WebGL, a page
error) emits ``failed`` once, and the panel goes back to the painted face.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtWidgets import QWidget

from arelis.paths import user_data_dir

WEB_DIR = Path(__file__).resolve().parent / "web"
GLB_ENV = "ARELIS_AVATAR_GLB"
_READY_TIMEOUT_MS = 30_000
_LOG = logging.getLogger("arelis.persona_face")
# PersonaPanel state -> window.avatar.setState name.
STATE_MAP = {
    "rest": "idle",
    "listening": "listening",
    "thinking": "thinking",
    "speaking": "speaking",
    "done": "done",
}


def glb_path() -> Path:
    override = os.environ.get(GLB_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return user_data_dir() / "avatar" / "ellah.glb"


def unavailable_reason() -> str | None:
    """Why the web avatar cannot start, or None when it may try."""
    if os.environ.get("ARELIS_WEB_AVATAR", "1").strip().lower() in {"0", "false", "no", "off"}:
        return "turned off by ARELIS_WEB_AVATAR"
    if not glb_path().is_file():
        return f"no model at {glb_path()}"
    if not (WEB_DIR / "index.html").is_file():
        return "scene files missing"
    try:
        from arelis.ui.solar_gl import gl_wanted

        # Same rule as the globe: no in-process Chromium beside a desktop GL share group.
        if gl_wanted():
            return "desktop GL is on (ARELIS_SOLAR_GL)"
    except Exception:
        pass
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except Exception as exc:
        return f"QtWebEngine unavailable: {exc}"
    return None


class WebAvatar(QWidget):
    """Hosts the scene. Call set_state and set_level; listen for failed."""

    failed = Signal(str)
    ready = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._ready = False
        self._dead = False
        self._state = "idle"
        self._level = -1.0
        self.view = QWebEngineView(self)
        # Clicks go to the panel underneath, which owns stop-speaking.
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        page = self.view.page()
        page.loadFinished.connect(self._loaded)
        page.renderProcessTerminated.connect(lambda *_: self._fail("render process ended"))
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._check)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(lambda: self._fail("scene did not report ready"))
        url = QUrl.fromLocalFile(str(WEB_DIR / "index.html"))
        query = QUrlQuery()
        query.addQueryItem("glb", QUrl.fromLocalFile(str(glb_path())).toString())
        url.setQuery(query)
        self._deadline.start(_READY_TIMEOUT_MS)
        self.view.load(url)

    def is_ready(self) -> bool:
        return self._ready and not self._dead

    def resizeEvent(self, event) -> None:
        self.view.setGeometry(self.rect())
        super().resizeEvent(event)

    def set_state(self, panel_state: str) -> None:
        name = STATE_MAP.get(panel_state, "idle")
        if name != self._state:
            self._state = name
            self._call(f"setState({json.dumps(name)})")

    def set_level(self, level: float | None) -> None:
        v = 0.0 if level is None else max(0.0, min(1.0, float(level)))
        if abs(v - self._level) >= 0.01:
            self._level = v
            self._call(f"setLevel({v:.3f})")

    def _call(self, expr: str) -> None:
        if self._ready and not self._dead:
            self.view.page().runJavaScript(f"window.avatar && window.avatar.{expr}")

    def _loaded(self, ok: bool) -> None:
        if not ok:
            self._fail("page failed to load")
        elif not self._dead:
            self._poll.start()

    def _check(self) -> None:
        js = (
            "JSON.stringify({ready: !!window.__ready, error: window.__error || null,"
            " api: !!(window.avatar && window.avatar.setState),"
            " gl: !!document.createElement('canvas').getContext('webgl2')})"
        )
        self.view.page().runJavaScript(js, 0, self._on_check)

    def _on_check(self, raw) -> None:
        if self._dead:
            return
        try:
            info = json.loads(raw or "{}")
        except (TypeError, ValueError):
            info = {}
        if not info.get("gl", True):
            self._fail("WebGL unavailable")
        elif info.get("error"):
            self._fail(f"scene error: {info['error']}")
        elif info.get("ready") and info.get("api") and not self._ready:
            self._ready = True
            self._poll.setInterval(2000)  # keep watching for a late error
            self._deadline.stop()
            self._call(f"setState({json.dumps(self._state)})")
            self.ready.emit()

    def _fail(self, reason: str) -> None:
        if self._dead:
            return
        self._dead = True
        self._poll.stop()
        self._deadline.stop()
        _LOG.warning("web avatar off, painted face kept: %s", reason)
        self.failed.emit(reason)
