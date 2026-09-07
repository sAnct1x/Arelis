"""Earth-zone Cesium plate.

Source-checkout + astro extra only. Missing WebEngine falls back to the
Qt globe. Tokens stay in Python and ride QWebChannel — never written
into the HTML on disk.

When the solar lab used GPU, Cesium is a child process
(`earth_globe_proc`). This process must not construct QWebEngineView
next to a desktop share group. Sodium HUD stays here. The HUD glass
is a translucent Tool overlay, masked to chrome so wheel and drag
reach Cesium. The Cesium plate itself stays opaque.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QRegion, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget

from arelis.earth.globe_stack import GlobeStack, choose_stack
from arelis.earth.lod import entity_lla
from arelis.earth.runtime import get_earth
from arelis.ui.earth_marks import heading_of

GLOBE_DIR = Path(__file__).resolve().parent / "earth_globe"
_CHILD_HWND_WAIT_MS = 12_000
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def globe_http_user_agent() -> str:
    """OSM tiles 403 unless Chromium names the app. Same token as tiles.py."""
    from arelis import __source_url__, __version__

    return f"Arelis/{__version__} (+{__source_url__})"


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def share_group_live() -> bool:
    """True while Qt still owns an application-wide GL share context."""
    try:
        from PySide6.QtGui import QOpenGLContext

        return QOpenGLContext.globalShareContext() is not None
    except Exception:
        return False


def globe_wants_own_process() -> bool:
    """Cesium leaves this process when solar GL / a share group is live.

    The child never nests. Pytest without ARELIS_SOLAR_GL stays in-process.
    Daily driver (GPU solar lab) always goes out of process — park() cannot
    kill QOpenGLContext.globalShareContext() while AA_ShareOpenGLContexts
    is an application attribute.
    """
    if _truthy("ARELIS_EARTH_GLOBE_CHILD"):
        return False
    raw = os.environ.get("ARELIS_EARTH_GLOBE_OOP", "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    try:
        from arelis.ui.solar_gl import gl_wanted

        if gl_wanted():
            return True
    except Exception:
        pass
    return share_group_live()


def globe_line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def parse_globe_line(raw: bytes | str) -> dict[str, Any] | None:
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    text = text.strip()
    if not text:
        return None
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        return None
    return msg if isinstance(msg, dict) else None


def _win_job_for(pid: int) -> int | None:
    """Kill-on-close job so QtWebEngineProcess.exe dies with the child."""
    if os.name != "nt" or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes

    job_object_limit_kill_on_job_close = 0x2000
    job_object_extended_limit_information = 9
    process_set_quota = 0x0100
    process_terminate = 0x0001

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
    if not kernel32.SetInformationJobObject(
        job,
        job_object_extended_limit_information,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        kernel32.CloseHandle(job)
        return None
    proc = kernel32.OpenProcess(process_set_quota | process_terminate, False, pid)
    if not proc:
        kernel32.CloseHandle(job)
        return None
    ok = kernel32.AssignProcessToJobObject(job, proc)
    kernel32.CloseHandle(proc)
    if not ok:
        kernel32.CloseHandle(job)
        return None
    return int(job)


def _close_win_job(handle: int | None) -> None:
    if not handle:
        return
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass


def chrome_mask(panel: QWidget) -> QRegion:
    """Hit region for painted chips only. Empty space belongs to Cesium."""
    region = QRegion()
    try:
        boxes = list(panel._chrome_rects())
    except Exception:
        boxes = []
    for box in boxes:
        if box is None or box.isEmpty():
            continue
        region = region.united(QRect(box).adjusted(-2, -2, 2, 2))
    return region


_SPACE = QColor(4, 5, 8)


def seal_globe_plate(widget: QWidget) -> None:
    """Same HWND rule as the main glass: opaque plate, no leftover frame.

    ``WA_TranslucentBackground`` on a native child is a layered window. The OS
    keeps the last bitmap and composites it through Cesium — the double limb
    and night-side marks. ``winId()`` on a sibling is the offset ghost
    (``window_resize.top_level_hwnd``). HUD chrome stays a Qt overlay.
    """
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
    widget.setAutoFillBackground(True)
    pal = widget.palette()
    pal.setColor(widget.backgroundRole(), _SPACE)
    widget.setPalette(pal)


class GlobeKeyHose(QObject):
    """Chromium eats WASD and Find. The sodium plate still owns those keys."""

    def __init__(self, deliver, *, gate=None) -> None:
        super().__init__()
        self._deliver = deliver
        self._gate = gate
        self._busy = False

    def eventFilter(self, _obj, event) -> bool:
        et = event.type()
        if et not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if self._busy:
            return False
        if self._gate is not None and not self._gate():
            return False
        self._busy = True
        try:
            self._deliver(event)
        finally:
            self._busy = False
        return True


def deliver_globe_key(panel: QWidget | None, event: QKeyEvent) -> None:
    if panel is None:
        return
    QApplication.sendEvent(panel, event)


def globe_key_payload(event: QKeyEvent) -> dict[str, Any]:
    return {
        "event": "key",
        "down": event.type() == QEvent.Type.KeyPress,
        "key": int(event.key()),
        "mod": int(event.modifiers()),
        "text": event.text() or "",
        "auto": bool(event.isAutoRepeat()),
    }


class EarthHudGlass(QWidget):
    """Same sodium HUD, parked over Cesium — not a second Earth UI.

    Cesium is a foreign HWND. A child of the solar plate paints *under*
    it (AA_DontCreateNativeWidgetSiblings). This is a Tool window of the
    Reality frame, masked to chrome, so Find / Leave / Live stay.

    Translucent on purpose: an opaque glass plus a Source fill of
    ``(0, 0, 0, 0)`` is a black plate on Windows. The Cesium host
    (``seal_globe_plate``) stays opaque — that layered-window rule is
    for native children, not this overlay.
    """

    def __init__(self, panel: QWidget) -> None:
        owner = panel.window()
        super().__init__(None if owner is panel else owner)
        self._panel = panel
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        panel.installEventFilter(self)
        if owner is not None and owner is not panel:
            owner.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._panel and event.type() == QEvent.Type.Hide:
            self.hide()
            return False
        if obj is self.window() or obj is self._panel.window():
            if event.type() in (
                QEvent.Type.Move,
                QEvent.Type.Resize,
                QEvent.Type.WindowStateChange,
            ):
                host = getattr(self._panel, "_globe_host", None)
                pin = getattr(host, "pin_child", None)
                if callable(pin):
                    pin()
                stack_chrome_over_globe(self, host)
        return False

    def paintEvent(self, _event) -> None:
        from arelis.ui.panels.solar_hud import paint_earth_chrome

        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(self._panel.font())
        paint_earth_chrome(self._panel, painter)
        after = chrome_mask(self._panel)
        if after.isEmpty():
            self.clearMask()
        elif after != self.mask():
            self.setMask(after)

    def _forward_mouse(self, event: QMouseEvent) -> None:
        gp = event.globalPosition()
        local = QPointF(self._panel.mapFromGlobal(gp.toPoint()))
        clone = QMouseEvent(
            event.type(),
            local,
            gp,
            event.button(),
            event.buttons(),
            event.modifiers(),
        )
        QApplication.sendEvent(self._panel, clone)

    def mousePressEvent(self, event) -> None:
        self._forward_mouse(event)

    def mouseMoveEvent(self, event) -> None:
        self._forward_mouse(event)

    def mouseReleaseEvent(self, event) -> None:
        self._forward_mouse(event)

    def wheelEvent(self, event) -> None:
        gp = event.globalPosition()
        local = QPointF(self._panel.mapFromGlobal(gp.toPoint()))
        clone = QWheelEvent(
            local,
            gp,
            event.pixelDelta(),
            event.angleDelta(),
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
        )
        QApplication.sendEvent(self._panel, clone)

    def keyPressEvent(self, event) -> None:
        self._panel.keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        self._panel.keyReleaseEvent(event)


def stack_chrome_over_globe(hud: QWidget | None, host: QWidget | None) -> None:
    """Pin the sodium HUD over the globe. No child winId — that is the ghost."""
    if hud is None:
        return
    panel = getattr(hud, "_panel", None)
    if panel is not None:
        if hud.parentWidget() is not None and not bool(
            hud.windowFlags() & Qt.WindowType.Window
        ):
            origin = panel.mapTo(hud.parentWidget(), QPoint(0, 0))
        else:
            origin = panel.mapToGlobal(QPoint(0, 0))
        hud.setGeometry(QRect(origin, panel.size()))
        mask = chrome_mask(panel)
        if mask.isEmpty():
            hud.clearMask()
        else:
            hud.setMask(mask)
    if host is not None:
        host.lower()
    hud.raise_()


class GlobeBridge(QObject):
    start = Signal(str)
    setCameraJson = Signal(str)
    releaseCamera = Signal()
    nudgeJson = Signal(str)
    lookJson = Signal(str)
    aimJson = Signal(str)
    upsertJson = Signal(str)
    placesJson = Signal(str)
    flyJson = Signal(str)
    stackJson = Signal(str)
    showStreets = Signal(bool)
    buildingsJson = Signal(str)
    roadsJson = Signal(str)
    marksJson = Signal(str)
    findOpen = Signal(bool)
    armRide = Signal(str)
    followJson = Signal(str)

    hostReady = Signal(str)
    hostFailed = Signal(str)
    hostPicked = Signal(str)
    hostRidden = Signal(str)
    hostCamera = Signal(str)
    hostGround = Signal(str)
    hostTiles = Signal(str)
    hostKey = Signal(str)

    @Slot()
    def hello(self) -> None:
        self.start.emit(json.dumps(choose_stack().to_payload()))

    @Slot(str)
    def tilesReady(self, kind: str) -> None:
        self.hostTiles.emit(kind)

    @Slot(str)
    def failed(self, why: str) -> None:
        self.hostFailed.emit(why)

    @Slot(str)
    def picked(self, entity_id: str) -> None:
        self.hostPicked.emit(entity_id)

    @Slot(str)
    def ridden(self, entity_id: str) -> None:
        self.hostRidden.emit(entity_id)

    @Slot(str)
    def cameraMoved(self, raw: str) -> None:
        self.hostCamera.emit(raw)

    @Slot(str)
    def groundPicked(self, raw: str) -> None:
        self.hostGround.emit(raw)

    @Slot(str)
    def ready(self, kind: str) -> None:
        self.hostReady.emit(kind)

    @Slot(str)
    def keyStruck(self, raw: str) -> None:
        """Chromium ate the Qt event. JS still saw the key."""
        self.hostKey.emit(raw)


def webengine_available() -> bool:
    """True when Cesium can run. Parent must not import WebEngine.

    Importing QtWebEngineWidgets initializes Chromium in this process.
    That is the AMD abort when a desktop share group still exists.
    The child imports. The parent only checks the spec.
    """
    if _truthy("ARELIS_EARTH_GLOBE_CHILD"):
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        except Exception:
            return False
        return True
    try:
        import importlib.util

        return importlib.util.find_spec("PySide6.QtWebEngineWidgets") is not None
    except Exception:
        return False


def prepare_chromium_for_shared_gl(
    env: MutableMapping[str, str] | None = None,
    *,
    share_live: bool | None = None,
) -> str:
    """Pin Chromium to software GL only while a desktop share group is live.

    After solar GL is destroyed for Enter Earth, pass share_live=False so
    Cesium can use the vendor GPU. Do not add --disable-gpu as a habit.
    """
    target = os.environ if env is None else env
    cur = str(target.get("QTWEBENGINE_CHROMIUM_FLAGS") or "")
    if share_live is False:
        return cur
    try:
        from PySide6.QtGui import QOpenGLContext

        shared = QOpenGLContext.globalShareContext()
    except Exception:
        shared = None
    live = bool(shared) if share_live is None else bool(share_live)
    if not live:
        return cur
    extra = "--disable-gpu --disable-gpu-compositing"
    if "--disable-gpu" in cur:
        return cur
    flags = (cur + " " + extra).strip()
    target["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
    return flags


class EarthGlobeHost(QWidget):
    """Earth-zone planet. Cesium is a child process when solar GL was live.

    In-process QWebEngineView stays for pytest / no share group. The daily
    driver must not construct WebEngine next to a desktop share context.
    """

    def __init__(
        self, parent: QWidget | None = None, *, process: str | None = None
    ) -> None:
        super().__init__(parent)
        self.ready = False
        self.failed = False
        self.kind = ""
        self._view = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._sock = None
        self._server = None
        self._job: int | None = None
        self._foreign = None
        self._pending: list[dict[str, Any]] = []
        self._buf = b""
        self._own_process = False
        self._closing = False
        self._hwnd = 0
        self._last_entities = None
        self._last_buildings = None
        self.bridge = GlobeBridge(self)
        self.bridge.hostReady.connect(self._on_ready)
        self.bridge.hostFailed.connect(self._on_failed)
        self.bridge.hostTiles.connect(self._on_tiles)
        self.bridge.hostKey.connect(self._on_js_key)
        seal_globe_plate(self)
        mode = process or "auto"
        if mode == "auto":
            mode = "out" if globe_wants_own_process() else "in"
        if mode == "out":
            self._own_process = True
            if not webengine_available():
                self.failed = True
                self.kind = "native"
                return
            self._start_remote()
            return
        self._start_in_process()

    def _start_in_process(self) -> None:
        if not webengine_available():
            self.failed = True
            self.kind = "native"
            return
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView

        from arelis.ui.solar_gl import trace

        prepare_chromium_for_shared_gl(share_live=False)
        try:
            trace("earth globe: construct QWebEngineView")
            self._view = QWebEngineView(self)
            trace("earth globe: QWebEngineView ok")
        except Exception:
            self.failed = True
            self.kind = "native"
            self._view = None
            return
        seal_globe_plate(self._view)
        self._view.page().setBackgroundColor(_SPACE)
        try:
            prof = self._view.page().profile()
            prof.setHttpUserAgent(globe_http_user_agent())
            prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        except Exception:
            pass
        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        self._view.loadFinished.connect(self._on_load)
        self._hose = GlobeKeyHose(
            lambda ev: deliver_globe_key(self.parent(), ev),
            gate=self._globe_has_focus,
        )
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._hose)
        channel = QWebChannel(self._view.page())
        channel.registerObject("bridge", self.bridge)
        self._view.page().setWebChannel(channel)
        index = GLOBE_DIR / "index.html"
        url = QUrl.fromLocalFile(str(index))
        stamp = str(int((GLOBE_DIR / "bridge.js").stat().st_mtime))
        url.setQuery(f"v={stamp}")
        self._view.setUrl(url)
        self._view.setGeometry(self.rect())

    def _start_remote(self) -> None:
        from PySide6.QtNetwork import QHostAddress, QTcpServer

        from arelis.ui.solar_gl import trace

        server = QTcpServer(self)
        if not server.listen(QHostAddress.SpecialAddress.LocalHost, 0):
            self.failed = True
            self.kind = "native"
            return
        self._server = server
        server.newConnection.connect(self._on_remote_connection)
        port = int(server.serverPort())
        root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["ARELIS_EARTH_GLOBE_CHILD"] = "1"
        env["ARELIS_EARTH_GLOBE_OOP"] = "0"
        env["ARELIS_SOLAR_GL"] = "0"
        env.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
        env.pop("QT_OPENGL", None)
        if sys.platform == "win32":
            env["QT_QPA_PLATFORM"] = "windows"
            env["ARELIS_ALLOW_OFFSCREEN"] = "1"
        from arelis.hidden_proc import hidden_kwargs

        trace(f"earth globe: spawn child port={port}")
        try:
            self._proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "arelis.ui.earth_globe_proc",
                    "--port",
                    str(port),
                ],
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                **hidden_kwargs(),
            )
        except OSError:
            self.failed = True
            self.kind = "native"
            server.close()
            self._server = None
            return
        self._job = _win_job_for(int(self._proc.pid))
        QTimer.singleShot(_CHILD_HWND_WAIT_MS, self._remote_timeout)

    def _on_remote_connection(self) -> None:
        if self._server is None:
            return
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        if self._sock is not None:
            sock.close()
            return
        self._sock = sock
        sock.readyRead.connect(self._on_remote_bytes)
        sock.disconnected.connect(self._on_remote_gone)
        for payload in self._pending:
            self._write_remote(payload)
        self._pending.clear()

    def _on_remote_bytes(self) -> None:
        sock = self._sock
        if sock is None:
            return
        self._buf += bytes(sock.readAll().data())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            msg = parse_globe_line(line)
            if msg is not None:
                self._on_remote_event(msg)

    def _on_remote_event(self, msg: dict[str, Any]) -> None:
        event = str(msg.get("event") or "")
        if event == "hwnd":
            try:
                hwnd = int(msg.get("hwnd") or 0)
            except (TypeError, ValueError):
                hwnd = 0
            if hwnd:
                self._embed_hwnd(hwnd)
            return
        if event == "ready":
            self.bridge.hostReady.emit(str(msg.get("kind") or ""))
            return
        if event == "failed":
            self.bridge.hostFailed.emit(str(msg.get("why") or ""))
            return
        if event == "picked":
            self.bridge.hostPicked.emit(str(msg.get("id") or ""))
            return
        if event == "ridden":
            self.bridge.hostRidden.emit(str(msg.get("id") or ""))
            return
        if event == "camera":
            self.bridge.hostCamera.emit(str(msg.get("raw") or ""))
            return
        if event == "ground":
            self.bridge.hostGround.emit(str(msg.get("raw") or ""))
            return
        if event == "tiles":
            self.bridge.hostTiles.emit(str(msg.get("kind") or ""))
            return
        if event == "key":
            self._deliver_remote_key(msg)

    def _on_js_key(self, raw: str) -> None:
        if self._own_process or self.parent() is None:
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(msg, dict):
            self._deliver_remote_key(msg)

    def _globe_has_focus(self) -> bool:
        widget = QApplication.focusWidget()
        while widget is not None:
            if widget is self or widget is self._view:
                return True
            widget = widget.parentWidget()
        return False

    def _deliver_remote_key(self, msg: dict[str, Any]) -> None:
        kind = (
            QEvent.Type.KeyPress if msg.get("down") else QEvent.Type.KeyRelease
        )
        try:
            key = int(msg.get("key") or 0)
        except (TypeError, ValueError):
            return
        try:
            mods = Qt.KeyboardModifier(int(msg.get("mod") or 0))
        except (TypeError, ValueError):
            mods = Qt.KeyboardModifier.NoModifier
        event = QKeyEvent(
            kind,
            key,
            mods,
            str(msg.get("text") or ""),
            bool(msg.get("auto")),
        )
        deliver_globe_key(self.parent(), event)

    def _embed_hwnd(self, hwnd: int) -> None:
        """Remember the child. Do not swallow it with createWindowContainer.

        DWM keeps the first blit of a foreign HWND. The HUD hopped to
        Singapore while the plate stayed the ISS still. The child is a
        real window that follows this plate.
        """
        if hwnd <= 0:
            return
        from arelis.ui.solar_gl import trace

        self._hwnd = hwnd
        self._foreign = None
        self._view = None
        trace(f"earth globe: child hwnd={hwnd} (not embedded)")
        self.pin_child()

    def pin_child(self) -> None:
        """Park the Cesium window on this plate in screen space."""
        if not self._own_process or self._hwnd <= 0:
            return
        top = self.mapToGlobal(QPoint(0, 0))
        self._write_remote(
            {
                "op": "place",
                "x": int(top.x()),
                "y": int(top.y()),
                "w": max(self.width(), 1),
                "h": max(self.height(), 1),
            }
        )
        panel = self.parentWidget()
        hud = getattr(panel, "_earth_hud", None) if panel is not None else None
        if hud is not None:
            stack_chrome_over_globe(hud, self)

    def _write_remote(self, payload: dict[str, Any]) -> None:
        sock = self._sock
        if sock is None:
            self._pending.append(payload)
            return
        sock.write(QByteArray(globe_line(payload)))
        sock.flush()

    def _remote_timeout(self) -> None:
        if self._closing or self._proc is None:
            return
        if self._own_process and self._hwnd == 0 and not self.failed:
            from arelis.ui.solar_gl import trace

            trace("earth globe: child hwnd timeout")
            self.failed = True
            self.kind = "native"
            self.bridge.hostFailed.emit("cesium")

    def _on_remote_gone(self) -> None:
        if self._closing or self.failed:
            return
        if self.ready:
            self.failed = True
            self.kind = "native"
            self.bridge.hostFailed.emit("cesium")
            return
        if self._hwnd == 0:
            self.failed = True
            self.kind = "native"
            self.bridge.hostFailed.emit("cesium")

    def shutdown(self) -> None:
        """Stop the Cesium child. In-process leave still deleteLater the view."""
        if not self._own_process:
            return
        self._closing = True
        self._write_remote({"op": "quit"})
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.disconnectFromHost()
            except Exception:
                pass
        server = self._server
        self._server = None
        if server is not None:
            server.close()
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=0.8)
                except Exception:
                    pass
        job = self._job
        self._job = None
        _close_win_job(job)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._view is not None:
            self._view.setGeometry(self.rect())
        self.pin_child()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.pin_child()

    def _on_ready(self, kind: str) -> None:
        self.ready = True
        self.kind = kind or choose_stack().label()
        self.push_marks()

    def _on_load(self, ok: bool) -> None:
        # Chromium emits loadFinished(False) for aborted about:blank and
        # some qrc subresources. JS reports a real Cesium miss itself.
        return

    def _on_failed(self, why: str) -> None:
        # Photoreal miss must not kill GIBS or the HUD.
        if why and why != "cesium":
            return
        self.failed = True
        self.kind = "native"
        self.hide()
        try:
            from arelis.physics.telemetry import emit

            emit("earth_globe", event="failed")
        except Exception:
            pass

    def _on_tiles(self, kind: str) -> None:
        self.ready = True
        self.kind = kind or self.kind
        self.push_marks()

    def stack(self) -> GlobeStack:
        return choose_stack()

    def push_camera(
        self,
        lat: float,
        lon: float,
        alt_m: float,
        heading: float | None = None,
        pitch: float | None = None,
        *,
        soft: bool = False,
        keep_ride: bool = False,
    ) -> None:
        payload: dict[str, float] = {
            "lat": max(-90.0, min(90.0, float(lat))),
            "lon": float(lon),
            "alt_m": max(200.0, min(8.0e7, float(alt_m))),
        }
        if heading is not None:
            payload["heading"] = heading
        if pitch is not None:
            payload["pitch"] = pitch
        if soft:
            payload["soft"] = 1.0
        if keep_ride:
            payload["keepRide"] = 1.0
        if self._own_process:
            remote = {"op": "camera", **payload}
            self._write_remote(remote)
            return
        self.bridge.setCameraJson.emit(json.dumps(payload))

    def release_camera(self) -> None:
        """Drop Cesium track / leftover lookAt so the next hop can land."""
        if self._own_process:
            self._write_remote({"op": "release"})
            return
        self.bridge.releaseCamera.emit()

    def _eval_js(self, src: str) -> None:
        view = self._view
        if view is None:
            return
        try:
            view.page().runJavaScript(src)
        except Exception:
            pass

    def arm_ride(self, entity_id: str) -> None:
        """Start JS follow. Do not go through upsert debounce or release."""
        eid = str(entity_id or "")
        if self._own_process:
            self._write_remote({"op": "ride", "id": eid})
            return
        self.bridge.armRide.emit(eid)
        self._eval_js(f"window.arelisArmRide && window.arelisArmRide({json.dumps(eid)})")

    def follow_lla(
        self,
        lat: float,
        lon: float,
        alt_m: float,
        heading: float,
        pitch: float,
    ) -> None:
        """Sit on a moving contact. Ignores a leftover hop goLock."""
        payload = {
            "lat": max(-90.0, min(90.0, float(lat))),
            "lon": float(lon),
            "alt_m": max(200.0, min(8.0e7, float(alt_m))),
            "heading": float(heading),
            "pitch": float(pitch),
        }
        raw = json.dumps(payload)
        if self._own_process:
            self._write_remote({"op": "follow", **payload})
            return
        self.bridge.followJson.emit(raw)
        self._eval_js(
            "(function(){"
            f"var p={raw};"
            "if(window.arelisFollowLla){window.arelisFollowLla(p);return;}"
            "var v=window.viewer;"
            "if(!v||typeof Cesium==='undefined')return;"
            "try{v.camera.cancelFlight();}catch(e){}"
            "v.camera.setView({"
            "destination:Cesium.Cartesian3.fromDegrees(p.lon,p.lat,p.alt_m),"
            "orientation:{"
            "heading:Cesium.Math.toRadians(p.heading||0),"
            "pitch:Cesium.Math.toRadians(p.pitch==null?-28:p.pitch),"
            "roll:0}});"
            "v.scene.requestRender();"
            "})()"
        )

    def push_nudge(self, fwd: float, right: float, up: float) -> None:
        payload = {"fwd": float(fwd), "right": float(right), "up": float(up)}
        if self._own_process:
            self._write_remote({"op": "nudge", **payload})
            return
        self.bridge.nudgeJson.emit(json.dumps(payload))

    def push_look(self, yaw: float, pitch: float) -> None:
        payload = {"yaw": float(yaw), "pitch": float(pitch)}
        if self._own_process:
            self._write_remote({"op": "look", **payload})
            return
        self.bridge.lookJson.emit(json.dumps(payload))

    def push_aim(self, lat: float, lon: float, alt_m: float) -> None:
        payload = {
            "lat": max(-90.0, min(90.0, float(lat))),
            "lon": float(lon),
            "alt_m": float(alt_m),
        }
        if self._own_process:
            self._write_remote({"op": "aim", **payload})
            return
        self.bridge.aimJson.emit(json.dumps(payload))

    def fly_to(self, lat: float, lon: float, alt_m: float) -> None:
        if self._own_process:
            self._write_remote(
                {"op": "fly", "lat": lat, "lon": lon, "alt_m": alt_m}
            )
            return
        self.bridge.flyJson.emit(json.dumps({"lat": lat, "lon": lon, "alt_m": alt_m}))

    def push_marks(self) -> None:
        if self._own_process:
            self._write_remote({"op": "marks"})
            return
        from arelis.ui.earth_marks import atlas_data_uris

        self.bridge.marksJson.emit(json.dumps(atlas_data_uris()))

    def push_entities(self, rows: list[dict[str, Any]]) -> None:
        key = _entity_push_key(rows)
        if key == self._last_entities:
            return
        self._last_entities = key
        if self._own_process:
            self._write_remote({"op": "entities", "rows": rows})
            return
        self.bridge.upsertJson.emit(json.dumps(rows))

    def push_places(self, rows: list[dict[str, Any]]) -> None:
        if self._own_process:
            self._write_remote({"op": "places", "rows": rows})
            return
        self.bridge.placesJson.emit(json.dumps(rows))

    def push_stack(self) -> None:
        if self._own_process:
            self._write_remote({"op": "stack"})
            return
        self.bridge.stackJson.emit(json.dumps(self.stack().to_payload()))

    def push_find(self, on: bool) -> None:
        """Tell Cesium Find is open so JS hoses keys and does not WASD-fly."""
        if self._own_process:
            self._write_remote({"op": "find", "on": bool(on)})
            return
        self.bridge.findOpen.emit(bool(on))

    def push_streets(self, on: bool) -> None:
        if self._own_process:
            self._write_remote({"op": "streets", "on": bool(on)})
        else:
            self.bridge.showStreets.emit(bool(on))
        self.push_roads([])

    def push_roads(self, rows: list[dict[str, Any]] | None = None) -> None:
        payload = road_rows() if rows is None else rows
        if self._own_process:
            self._write_remote({"op": "roads", "rows": payload})
            return
        self.bridge.roadsJson.emit(json.dumps(payload))

    def push_buildings(self, rings: list[list[list[float]]] | None = None) -> None:
        payload = building_rows() if rings is None else rings
        key = (len(payload), payload[0][0] if payload and payload[0] else None)
        if key == self._last_buildings:
            return
        self._last_buildings = key
        if self._own_process:
            self._write_remote({"op": "buildings", "rings": payload})
            return
        self.bridge.buildingsJson.emit(json.dumps(payload))


# City eye looks at the street. The store still holds the catalog.
_CITY_ORBIT_MARKS = 0
_APPROACH_ORBIT_MARKS = 16


def _entity_push_key(rows: list[dict[str, Any]]) -> tuple[Any, ...]:
    return tuple(
        (
            row.get("id"),
            round(float(row.get("lat") or 0.0), 3),
            round(float(row.get("lon") or 0.0), 3),
            int(row.get("alt_m") or 0),
            int(float(row.get("vx") or 0.0)),
            int(float(row.get("vy") or 0.0)),
            int(float(row.get("vz") or 0.0)),
            int(float(row.get("when_unix") or 0.0)),
            row.get("freshness") or "",
            bool(row.get("hot")),
            bool(row.get("ride")),
            row.get("card") or "",
        )
        for row in rows
    )


def pick_orbit_marks(
    rows: list[dict[str, Any]],
    *,
    cap: int = _CITY_ORBIT_MARKS,
    keep_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Tracked marks always. City/near keep no sat swarm — only a hot ISS."""
    held = keep_ids or set()
    orbit = [row for row in rows if row.get("layer") in {"satellites", "iss"}]
    ground = [row for row in rows if row.get("layer") not in {"satellites", "iss"}]
    iss = [
        row
        for row in orbit
        if row.get("layer") == "iss"
        and (row.get("hot") or str(row.get("id") or "") in held)
    ]
    sats = [row for row in orbit if row.get("layer") == "satellites"]
    pinned = [
        row
        for row in sats
        if row.get("hot") or str(row.get("id") or "") in held
    ]
    pinned_ids = {str(row.get("id") or "") for row in pinned}
    rest = [row for row in sats if str(row.get("id") or "") not in pinned_ids]
    return ground + iss + pinned + rest[: max(0, cap - len(pinned))]


def entity_rows() -> list[dict[str, Any]]:
    zone = get_earth()
    if zone is None or not zone.active:
        return []
    out: list[dict[str, Any]] = []
    track = zone.track_id
    ride = zone.ride_id
    band = zone.last_view.band if zone.last_view is not None else "space"
    from arelis.earth.frames import ecef_to_geodetic
    from arelis.ui.earth_overlay import inspect_card_text

    for ent in zone.visible():
        if ent.layer == "people":
            continue
        pair = entity_lla(ent)
        if pair is None:
            continue
        lat, lon = pair
        meta = ent.meta or {}
        try:
            alt = float(meta.get("alt") or meta.get("alt_m") or 0.0)
        except (TypeError, ValueError):
            alt = 0.0
        if (
            ent.layer in {"satellites", "iss"}
            or alt <= 0.0
            or ent.freshness in {"stale", "dead-reckoned"}
        ):
            try:
                geo_lat, geo_lon, geo_alt = ecef_to_geodetic(ent.x, ent.y, ent.z)
            except Exception:
                geo_lat, geo_lon, geo_alt = lat, lon, 0.0
            lat, lon = geo_lat, geo_lon
            if geo_alt > 80.0 or ent.layer in {"satellites", "iss"}:
                alt = geo_alt
            elif alt <= 0.0:
                alt = max(0.0, geo_alt)
        heading = heading_of(ent)
        hot = ent.id in {track, ride}
        try:
            pose_at = float((ent.meta or {}).get("_pose_unix") or ent.when_unix or 0.0)
        except (TypeError, ValueError):
            pose_at = float(ent.when_unix or 0.0)
        out.append(
            {
                "id": ent.id,
                "layer": ent.layer,
                "mark": ent.layer,
                "label": ent.label,
                "lat": lat,
                "lon": lon,
                "alt_m": alt,
                "band": band,
                "heading_deg": heading,
                "freshness": ent.freshness,
                "hot": hot,
                "ride": bool(ride) and ent.id == ride,
                "group": str((ent.meta or {}).get("group") or ""),
                "card": inspect_card_text(ent) if hot else "",
                "x": ent.x,
                "y": ent.y,
                "z": ent.z,
                "vx": ent.vx,
                "vy": ent.vy,
                "vz": ent.vz,
                "when_unix": pose_at,
            }
        )
    held = {track, ride} - {""}
    if band == "space":
        return out
    if band == "approach":
        return pick_orbit_marks(out, keep_ids=held, cap=_APPROACH_ORBIT_MARKS)
    return pick_orbit_marks(out, keep_ids=held, cap=_CITY_ORBIT_MARKS)


def place_rows(band: str, lat: float, lon: float) -> list[dict[str, Any]]:
    from arelis.earth.land import places, places_dense

    if band == "space":
        return []
    found = places_dense() if band in {"near", "city"} else places()
    ranked = sorted(
        found,
        key=lambda row: (row[1] - lat) ** 2
        + (((row[2] - lon + 180.0) % 360.0) - 180.0) ** 2,
    )
    cap = 8 if band == "approach" else 18 if band == "near" else 36
    return [{"name": n, "lat": a, "lon": b} for n, a, b in ranked[:cap]]


def road_rows() -> list[dict[str, Any]]:
    """Highway overlay for Cesium. Empty when Streets is off."""
    from arelis.earth.roads import roads_for_view

    zone = get_earth()
    if zone is None or not zone.active or not zone.tiles:
        return []
    view = zone.last_view
    if view is None:
        return []
    return roads_for_view(view.lat, view.lon, view.band, alt_m=view.alt_m)


def building_rows() -> list[list[list[float]]]:
    """Footprints are gone. Cesium already is the city."""
    return []
