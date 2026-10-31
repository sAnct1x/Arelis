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


def _glb_candidates() -> list[Path]:
    """Where the model may be, in order. The env override, when set, is the only one."""
    override = os.environ.get(GLB_ENV, "").strip()
    if override:
        return [Path(override).expanduser()]
    found = [user_data_dir() / "avatar" / "ellah.glb"]
    # On a source checkout user_data_dir() is the repo, but the model is
    # downloaded to the installed copy's folder. Look there too.
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        installed = Path(local) / "Arelis" / "avatar" / "ellah.glb"
        if installed != found[0]:
            found.append(installed)
    return found


def glb_path() -> Path:
    candidates = _glb_candidates()
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def unavailable_reason() -> str | None:
    """Why the web avatar cannot start, or None when it may try."""
    reason = _unavailable_reason()
    if reason is not None:
        _LOG.warning("web avatar off, painted face kept: %s", reason)
    return reason


def _unavailable_reason() -> str | None:
    if os.environ.get("ARELIS_WEB_AVATAR", "1").strip().lower() in {"0", "false", "no", "off"}:
        return "turned off by ARELIS_WEB_AVATAR"
    if not glb_path().is_file():
        checked = ", ".join(str(path) for path in _glb_candidates())
        return f"no model at {glb_path()} (checked {checked})"
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


def check_script(*, probe_gl: bool) -> str:
    """The page poll. WebGL is probed once, and the probe gives its context back.

    Chromium keeps about 16 WebGL contexts per page and drops the oldest past
    that. A detached test canvas stays active until GC, so probing on every
    poll (4 a second, then every 2 s) used up the budget and the page dropped
    the scene's own renderer, the oldest: no avatar, or a missed ready and
    the painted head.
    """
    gl = ""
    if probe_gl:
        gl = (
            ", gl: (() => { const g = document.createElement('canvas').getContext('webgl2');"
            " const lose = g && g.getExtension('WEBGL_lose_context');"
            " if (lose) lose.loseContext(); return !!g; })()"
        )
    return (
        "JSON.stringify({ready: !!window.__ready, error: window.__error || null,"
        " api: !!(window.avatar && window.avatar.setState)" + gl + "})"
    )


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
        self._gl_known = False
        self.view = QWebEngineView(self)
        # Clicks go to the panel underneath, which owns stop-speaking.
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        page = self.view.page()
        # See-through dock: the scene clears to alpha 0 under ?transparent=1.
        page.setBackgroundColor(Qt.GlobalColor.transparent)
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
        query.addQueryItem("transparent", "1")
        from arelis.ui.void_idle import aether_hue_shift

        self._tint = aether_hue_shift()
        query.addQueryItem("hue", str(self._tint))
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

    def refresh_theme_icons(self) -> None:
        """Theme-change hook (settings_host): retint her to the new room."""
        from arelis.ui.void_idle import aether_hue_shift

        self._tint = aether_hue_shift()
        self._call(f"setTint({self._tint})")

    def _call(self, expr: str) -> None:
        if self._ready and not self._dead:
            self.view.page().runJavaScript(f"window.avatar && window.avatar.{expr}")

    def _loaded(self, ok: bool) -> None:
        if not ok:
            self._fail("page failed to load")
        elif not self._dead:
            self._poll.start()

    def _check(self) -> None:
        self.view.page().runJavaScript(check_script(probe_gl=not self._gl_known), 0, self._on_check)

    def _on_check(self, raw) -> None:
        if self._dead:
            return
        try:
            info = json.loads(raw or "{}")
        except (TypeError, ValueError):
            info = {}
        if "gl" in info:
            self._gl_known = True
        if not info.get("gl", True):
            self._fail("WebGL unavailable")
        elif info.get("error"):
            self._fail(f"scene error: {info['error']}")
        elif info.get("ready") and info.get("api") and not self._ready:
            self._ready = True
            self._poll.setInterval(2000)  # keep watching for a late error
            self._deadline.stop()
            self._call(f"setState({json.dumps(self._state)})")
            self._call(f"setTint({self._tint})")
            self.ready.emit()

    def _fail(self, reason: str) -> None:
        if self._dead:
            return
        self._dead = True
        self._poll.stop()
        self._deadline.stop()
        _LOG.warning("web avatar off, painted face kept: %s", reason)
        self.failed.emit(reason)
