"""Her three.js figure in a QWebEngineView. This is the only face she has.

The scene ships in ``web/`` next to this file and loads over file:// only. The
model is not shipped: it is read from the user's data folder (or
``ARELIS_AVATAR_GLB``). Any failure (no QtWebEngine, no model, no WebGL, a page
error) emits ``failed`` once, and the panel keeps its neutral loading veil.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from arelis.paths import user_data_dir

WEB_DIR = Path(__file__).resolve().parent / "web"
GLB_ENV = "ARELIS_AVATAR_GLB"
CLIPS_ENV = "ARELIS_AVATAR_CLIPS"
_READY_TIMEOUT_MS = 30_000
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


def clips_path() -> Path:
    """Her body clips (anim-mixer.js). Required: without them her body holds its rest pose."""
    override = os.environ.get(CLIPS_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return glb_path().parent / "ellah-anim.glb"


def check_clips() -> bool:
    """True when the clips file is there; else one ERROR line naming where it must go."""
    path = clips_path()
    if path.is_file():
        return True
    logging.getLogger("arelis.avatar").error("[avatar] clips missing at %s", path)
    return False


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


def check_script(*, probe_gl: bool) -> str:
    """The page poll. WebGL is probed once, and the probe gives its context back.

    Chromium keeps about 16 WebGL contexts per page and drops the oldest past
    that. A detached test canvas stays active until GC, so probing on every
    poll (4 a second, then every 2 s) used up the budget and the page dropped
    the scene's own renderer, the oldest: no avatar, or a missed ready and
    no avatar.
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


_JS_LEVELS = {0: logging.INFO, 1: logging.WARNING, 2: logging.ERROR}


_UNROLL_NOTE = "warning X3557: loop only executes for 1 iteration(s), forcing loop to unroll"


def forward_console(level: int, message: str, line: int, source: str) -> None:
    """One page console line into the app log, under the ``[avatar]`` prefix."""
    from arelis.ui.persona_face.panel import LOG

    text = str(message)
    level_no = _JS_LEVELS.get(int(level), logging.INFO)
    if text.startswith("[avatar] "):
        text = text[len("[avatar] ") :]
    elif _UNROLL_NOTE in text:
        # The D3D compiler's note that a one-pass loop was unrolled (three.js
        # light loops with one light). Not a fault and nothing to act on, so it
        # is a single short info line, not a WARNING with the whole info log.
        LOG.info("[avatar] shader note unroll")
        return
    else:
        text = f"js {text} ({Path(str(source)).name}:{line})"
    LOG.log(level_no, "[avatar] %s", text)


def _console_page(parent):
    """A page that hands every console message to forward_console."""
    from PySide6.QtWebEngineCore import QWebEnginePage

    class _Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source) -> None:
            forward_console(getattr(level, "value", level), message, line, source)

    return _Page(parent)


def backdrop_color() -> QColor:
    """Her page background: transparent, or the room's bg0 under the opaque A/B arm."""
    from arelis.ui import idle_ab
    from arelis.ui.theme import color

    return color("bg0") if idle_ab.opaque_backdrop() else QColor(Qt.GlobalColor.transparent)


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
        self.view.setPage(_console_page(self.view))
        # She never takes a click: stop is the stop button or a spoken "stop".
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        page = self.view.page()
        # See-through dock: the scene clears to alpha 0 under ?transparent=1.
        # ARELIS_AVATAR_BACKDROP=opaque (blank-frame A/B) paints the room colour
        # under her instead, so Qt composes her view as an opaque widget.
        page.setBackgroundColor(backdrop_color())
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
        query.addQueryItem("clips", QUrl.fromLocalFile(str(clips_path())).toString())
        query.addQueryItem("transparent", "1")
        from arelis.ui import idle_ab

        # Diagnostic (idle_ab): her canvas without preserveDrawingBuffer.
        query.addQueryItem("pdb", "1" if idle_ab.preserve_buffer() else "0")
        from arelis.ui.void_idle import aether_hue_shift

        self._tint = aether_hue_shift()
        query.addQueryItem("hue", str(self._tint))
        url.setQuery(query)
        from arelis.ui.persona_face.panel import alog

        glb = glb_path()
        alog("glb load", path=glb, bytes=glb.stat().st_size if glb.is_file() else 0)
        clips = clips_path()
        if check_clips():
            alog("clips load", path=clips, bytes=clips.stat().st_size)
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

    def refit(self) -> None:
        """The layout settled: the page takes its size, refits her and draws a frame."""
        self._call("refit()")

    def refresh_theme_icons(self) -> None:
        """Theme-change hook (settings_host): retint her to the new room."""
        from arelis.ui.persona_face.panel import alog
        from arelis.ui.theme_tokens import active_theme
        from arelis.ui.void_idle import aether_hue_shift

        self._tint = aether_hue_shift()
        alog("theme", name=active_theme(), tint=self._tint)
        self.view.page().setBackgroundColor(backdrop_color())
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
            from arelis.ui.persona_face.panel import alog

            alog("ready")
            self.ready.emit()

    def _fail(self, reason: str) -> None:
        if self._dead:
            return
        self._dead = True
        self._poll.stop()
        self._deadline.stop()
        from arelis.ui.persona_face.panel import LOG

        LOG.warning("[avatar] failed reason=%r", reason)
        self.failed.emit(reason)
