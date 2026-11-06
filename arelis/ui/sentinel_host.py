"""Sentinels window: inset frameless host for the bridge Overseer page.

Hosts the bridge's Overseer in a QWebEngineView. The session token rides in
the URL fragment and is never logged. When the Sentinel child is down the
window shows "Sentinel offline" with a Start button. Theme colours follow
the active Arelis theme. Opening fades Arelis and the orbit tree to 20
percent; close, quit, or an error restores them.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QKeySequence, QPainter, QRegion, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arelis import sentinel_control
from arelis.ui import overseer_runtime
from arelis.ui.sentinel_presence import PresenceController, inset_geometry, mote_pos
from arelis.ui.theme_tokens import COLORS, active_theme

log = logging.getLogger(__name__)

_POLL_MS = 500
_POLL_TRIES = 24


def _reduced_motion() -> bool:
    try:
        from PySide6.QtGui import QGuiApplication

        hints = QGuiApplication.styleHints()
        fn = getattr(hints, "animationsEnabled", None)
        if callable(fn):
            return not bool(fn())
    except Exception:
        # Style hints or the animations query are missing on this Qt build.
        # Treat motion as allowed rather than invent a reduced-motion state.
        return False
    return False


class SentinelMote(QWidget):
    """Idle mote below the orbit. Click opens the Sentinels window."""

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self.setObjectName("SentinelMote")
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Sentinels")
        self._owner = owner
        owner.installEventFilter(self)
        self.show()
        self.raise_()
        self.reposition()

    def reposition(self) -> None:
        if self._owner is None:
            return
        x, y = mote_pos(self._owner.width(), self._owner.height())
        self.move(QPoint(max(0, x - 11), max(0, y - 11)))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._owner and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
        ):
            self.reposition()
        return super().eventFilter(watched, event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            open_sentinel_window(self._owner)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#a78bfa"))
        painter.setOpacity(0.35)
        painter.drawEllipse(1, 1, 20, 20)
        painter.setOpacity(0.8)
        painter.setBrush(QColor("#e2d6ff"))
        painter.drawEllipse(6, 6, 10, 10)


class SentinelWindow(QWidget):
    """Top-level inset Sentinels window: Overseer page, or the offline card."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(None)
        self._owner = parent
        self.presence = PresenceController()
        self.setObjectName("SentinelWindow")
        self.setWindowTitle("Sentinels")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._view = None
        self._scene = None
        self._live = None
        self._loaded_url: str | None = None
        self._tries = 0
        self._error = ""
        self._overlay_flags: dict = {}
        self._prev_lods: dict[str, int] = {}
        self._particle_paths: list = []
        self._entry_reverse = False
        self._entry_timer = QTimer(self)
        self._entry_timer.setInterval(16)
        self._entry_timer.timeout.connect(self._entry_tick)
        self._snap_timer = QTimer(self)
        self._snap_timer.setInterval(250)
        self._snap_timer.timeout.connect(self._poll_snapshot)
        self._mask_timer = QTimer(self)
        self._mask_timer.setInterval(250)
        self._mask_timer.timeout.connect(self._read_overlay_flags)

        self._stack = QStackedWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stack)

        self._offline = QWidget(self)
        off = QVBoxLayout(self._offline)
        off.addStretch(1)
        self.offline_label = QLabel("Sentinel offline", self._offline)
        self.offline_label.setObjectName("SentinelOfflineLabel")
        self.start_button = QPushButton("Start", self._offline)
        self.start_button.setObjectName("SentinelStartButton")
        self.start_button.clicked.connect(self.start_sentinel)
        off.addWidget(self.offline_label, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        off.addWidget(self.start_button, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        off.addStretch(1)
        self._stack.addWidget(self._offline)

        self._close_mote = QPushButton("x", self)
        self._close_mote.setObjectName("SentinelCloseMote")
        self._close_mote.setToolTip("Close (Esc)")
        self._close_mote.setFixedSize(28, 28)
        self._close_mote.clicked.connect(self.close)
        self._close_mote.raise_()

        self._hud_bar = QWidget(self)
        self._hud_bar.setObjectName("SentinelHudBar")
        self._hud_bar.setFixedHeight(36)
        hud_row = QHBoxLayout(self._hud_bar)
        hud_row.setContentsMargins(16, 4, 72, 4)
        hud_row.setSpacing(14)
        self._hud_labels: dict[str, QLabel] = {}
        for key, title in (
            ("units", "Units"),
            ("warden", "Warden"),
            ("stalker", "Stalker"),
            ("harvester", "Harvest"),
            ("sanitizer", "Sanitize"),
            ("tripwire", "Tripwire"),
        ):
            lab = QLabel(f"{title} 0", self._hud_bar)
            lab.setObjectName(f"SentinelHud_{key}")
            lab.setAccessibleName(f"{title} 0")
            self._hud_labels[key] = lab
            hud_row.addWidget(lab)
        hud_row.addStretch(1)
        self._hud_bar.move(8, 8)
        self._hud_bar.raise_()

        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._poll_tick)
        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        if parent is not None:
            parent.installEventFilter(self)
        self.apply_theme()
        self._sync_inset()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._owner and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
        ):
            self._sync_inset()
        return super().eventFilter(watched, event)

    def _sync_inset(self) -> None:
        owner = self._owner
        if owner is None:
            self.resize(1200, 780)
            self._place_hud(1200)
            return
        geo = owner.geometry()
        x, y, w, h = inset_geometry(geo.width(), geo.height())
        self.setGeometry(geo.x() + x, geo.y() + y, w, h)
        self._close_mote.move(max(8, w - 46), 48)
        self._place_hud(w)

    def apply_theme(self) -> None:
        bg = COLORS.get("bg0", "#0b0714")
        text = COLORS.get("text", "#e0d4ff")
        accent = COLORS.get("accent", "#a78bfa")
        well = COLORS.get("well", "rgba(14, 9, 32, 255)")
        theme = active_theme()
        self.setProperty("sentinelTheme", theme)
        self.setStyleSheet(
            f"#SentinelWindow, QStackedWidget, QWidget {{ background: {bg}; color: {text}; }}"
            f"#SentinelOfflineLabel {{ font-size: 18px; qproperty-alignment: AlignCenter; }}"
            f"#SentinelStartButton {{ background: {well}; color: {text};"
            f" border: 1px solid {accent}; padding: 6px 18px; }}"
            f"#SentinelCloseMote {{ background: #d9ccff; color: #1c1430;"
            f" border: 2px solid {accent}; border-radius: 14px; }}"
            f"#SentinelHudBar {{ background: rgba(14, 9, 32, 180); color: {text}; }}"
            f"#SentinelHudBar QLabel {{ color: {text}; font-size: 13px; }}"
        )
        self._push_theme_to_page(theme)

    def _push_theme_to_page(self, theme: str) -> None:
        view = self._view
        if view is None:
            return
        page = getattr(view, "page", lambda: None)()
        if page is None or not hasattr(page, "runJavaScript"):
            return
        safe = theme.replace("\\", "").replace('"', "")
        page.runJavaScript(
            f'document.documentElement.setAttribute("data-theme","{safe}");'
            f'window.dispatchEvent(new CustomEvent("arelis-theme",{{detail:"{safe}"}}));'
            'var c=document.getElementById("overseer-canvas");'
            'if(c){c.style.display="none";}'
            "['hud-topbar','hud-left','hud-right','hud-console'].forEach("
            "function(id){var el=document.getElementById(id);if(el)el.style.display='none';});"
        )

    def is_offline(self) -> bool:
        return self._stack.currentWidget() is self._offline

    def last_error(self) -> str:
        return self._error

    def refresh(self) -> None:
        """Show the Overseer if the child is up, else the offline card."""
        url = sentinel_control.overseer_url()
        if not url:
            self.offline_label.setText("Sentinel offline")
            self._stack.setCurrentWidget(self._offline)
            return
        view = self._ensure_view()
        if view is None:
            self._error = "Sentinel is running, but this window can't show it right now"
            self.offline_label.setText(self._error)
            self._stack.setCurrentWidget(self._offline)
            self._restore_presence("error")
            return
        self._error = ""
        if url != self._loaded_url:
            self._loaded_url = url
            if self._view is not None:
                self._view.setUrl(QUrl(url))
        self._stack.setCurrentWidget(view)
        self._push_theme_to_page(active_theme())
        self.start_entry_sequence()

    def _asset_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "assets" / "sentinel" / "overseer"

    def _ensure_scene(self):
        if self._scene is not None:
            return self._scene
        try:
            from PySide6.QtQuickWidgets import QQuickWidget
        except ImportError:
            log.warning("Sentinels window: Qt Quick widget unavailable")
            return None
        qml = self._asset_dir() / "OverseerView.qml"
        if not qml.is_file():
            log.warning("Sentinels window: OverseerView.qml missing at %s", qml)
            return None
        widget = QQuickWidget(self)
        widget.setObjectName("OverseerScene")
        widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        widget.setClearColor(QColor("#0b0714"))
        widget.setSource(QUrl.fromLocalFile(str(qml)))
        self._scene = widget
        return widget

    def start_entry_sequence(self) -> None:
        scene = self._ensure_scene()
        if scene is None:
            return
        root = scene.rootObject()
        reduced = _reduced_motion()
        if root is not None:
            root.setProperty(
                "cameraDistance", overseer_runtime.DEFAULT_CAMERA_DISTANCE
            )
            root.setProperty(
                "cameraPitch",
                overseer_runtime.pitch_deg(overseer_runtime.DEFAULT_CAMERA_DISTANCE),
            )
            if hasattr(root, "setParticles"):
                root.setParticles([])
        self._entry_timer.start()
        if sentinel_control.overseer_url():
            self._poll_snapshot()
        if root is not None and hasattr(root, "startEntry"):
            root.startEntry(reduced)
        if not self._particle_paths:
            self._particle_paths = overseer_runtime.particle_paths(
                [], width=max(1, self.width()), height=max(1, self.height())
            )
        self.apply_hud_mask()
        self._mask_timer.start()
        if sentinel_control.overseer_url():
            self._snap_timer.start()

    def _ensure_view(self):
        if self._live is not None:
            return self._live
        scene = self._ensure_scene()
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            log.warning("Sentinels window: QtWebEngine unavailable")
            if scene is None:
                return None
            self._live = scene
            self._stack.addWidget(scene)
            return self._live
        from PySide6.QtWidgets import QGridLayout

        live = QWidget(self)
        live.setObjectName("OverseerLive")
        grid = QGridLayout(live)
        grid.setContentsMargins(0, 0, 0, 0)
        if scene is not None:
            grid.addWidget(scene, 0, 0)
        self._view = QWebEngineView(live)
        self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        page = self._view.page()
        if page is not None and hasattr(page, "setBackgroundColor"):
            page.setBackgroundColor(QColor(0, 0, 0, 0))
        grid.addWidget(self._view, 0, 0)
        self._live = live
        self._stack.addWidget(live)
        return live


    def apply_hud_mask(self) -> None:
        """Keep mouse events on HUD plates; let the 3D view receive the hole."""
        if self._view is None:
            return
        w, h = max(1, self.width()), max(1, self.height())
        flags = self._overlay_flags or {}
        region = QRegion()
        for x, y, rw, rh in overseer_runtime.hud_mask_rects(
            w,
            h,
            emp=bool(flags.get("emp")),
            badges=bool(flags.get("badges")),
            full=bool(flags.get("modal") or flags.get("help")),
            qml_hud=True,
        ):
            region = region.united(QRegion(x, y, rw, rh))
        self._view.setMask(region)

    def _read_overlay_flags(self) -> None:
        view = self._view
        if view is None:
            return
        page = view.page()
        js = (
            "(function(){function vis(id){var el=document.getElementById(id);"
            "return !!(el && !el.classList.contains('hidden'));}"
            "return {emp:vis('emp-banner'),modal:vis('dossier-modal'),"
            "help:vis('help-overlay'),badges:vis('caste-badges')};})()"
        )
        page.runJavaScript(js, self._on_overlay_flags)

    def _on_overlay_flags(self, flags) -> None:
        self._overlay_flags = flags if isinstance(flags, dict) else {}
        self.apply_hud_mask()

    def _place_hud(self, width: int) -> None:
        bar = getattr(self, "_hud_bar", None)
        if bar is None:
            return
        bar.setFixedWidth(max(1, int(width) - 16))
        bar.move(8, 8)
        bar.hide()
        self._close_mote.raise_()

    def apply_hud_counts(self, units: list) -> None:
        """Show authenticated snapshot caste counts. Never invents numbers."""
        counts = {
            "warden": 0,
            "stalker": 0,
            "harvester": 0,
            "sanitizer": 0,
            "tripwire": 0,
        }
        for unit in units or []:
            caste = str(unit.get("caste") or "").lower()
            if caste in counts:
                counts[caste] += 1
        total = sum(counts.values())
        titles = {
            "units": ("Units", total),
            "warden": ("Warden", counts["warden"]),
            "stalker": ("Stalker", counts["stalker"]),
            "harvester": ("Harvest", counts["harvester"]),
            "sanitizer": ("Sanitize", counts["sanitizer"]),
            "tripwire": ("Tripwire", counts["tripwire"]),
        }
        for key, (title, n) in titles.items():
            lab = self._hud_labels.get(key)
            if lab is None:
                continue
            text = f"{title} {n}"
            lab.setText(text)
            lab.setAccessibleName(text)
        self._place_hud(max(1, self.width()))

    def _qml_list_prop(self, root, name: str) -> list:
        value = root.property(name) if root is not None else None
        to_var = getattr(value, "toVariant", None)
        if callable(to_var):
            value = to_var()
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        try:
            return list(value)
        except TypeError:
            return []

    def _wire_hud(self, root) -> None:
        if getattr(self, "_hud_wired", False) or root is None:
            return
        chrome = None
        from PySide6.QtCore import QObject

        for child in root.findChildren(QObject):
            if child.objectName() == "OverseerHud":
                chrome = child
                break
        if chrome is None or not hasattr(chrome, "hudCommand"):
            return
        chrome.hudCommand.connect(self._on_hud_command)
        self._hud_wired = True

    def _on_hud_command(self, name: str, payload) -> None:
        """Forward HUD actions along existing Overseer routes only."""
        data = payload if isinstance(payload, dict) else {}
        target = sentinel_control.bridge_target()
        status = ""
        if name == "focus":
            status = ""
        elif name == "retask" and not str(data.get("query") or "").strip():
            status = "Unavailable: retask needs a mission query (existing dispatch_task)"
        elif target is None:
            status = "Unavailable: Sentinel is not connected"
        else:
            host, port, token = target
            try:
                if name == "emp_halt":
                    overseer_runtime.post_overseer(
                        host, port, token, "/api/overseer/emp",
                        {"reason": str(data.get("reason") or "Overseer emergency stop")},
                    )
                    status = "Emergency stop requested"
                elif name == "dispatch":
                    overseer_runtime.post_overseer(
                        host, port, token, "/api/overseer/mission",
                        {
                            "mode": str(data.get("mode") or "multi"),
                            "query": str(data.get("query") or ""),
                        },
                    )
                    status = "Mission requested"
                elif name == "recall":
                    caste = str(data.get("caste") or "")
                    if not caste:
                        status = "Unavailable: recall needs a caste (existing scale route)"
                    else:
                        overseer_runtime.post_overseer(
                            host, port, token, "/api/overseer/scale",
                            {"caste": caste, "delta": -1},
                        )
                        status = "Recall requested for one idle unit of that caste"
                elif name == "retire":
                    overseer_runtime.post_overseer(
                        host, port, token, "/api/command",
                        {"op": "retire_unit", "unit_id": str(data.get("unit_id") or "")},
                    )
                    status = "Retire requested"
                elif name == "retask":
                    overseer_runtime.post_overseer(
                        host, port, token, "/api/command",
                        {
                            "op": "dispatch_task",
                            "caste": str(data.get("caste") or "harvester"),
                            "unit_id": data.get("unit_id"),
                            "payload": {"query": str(data.get("query") or "")},
                        },
                    )
                    status = "Retask requested"
                else:
                    status = f"Unavailable: no existing route for {name}"
            except Exception:
                log.warning("Sentinels window: HUD command %s failed", name)
                status = "Request failed"
        scene = self._scene
        root = scene.rootObject() if scene is not None else None
        if root is not None:
            root.setProperty("hudCommandStatus", status)
            root.setProperty("lastHudCommand", name)

    def apply_snapshot(self, snap: dict) -> dict:
        """Push a live hive snapshot into the native View3D. Returns the frame."""
        units = overseer_runtime.snapshot_units(snap)
        root = None
        scene = self._scene
        if scene is not None:
            root = scene.rootObject()
        distance = overseer_runtime.DEFAULT_CAMERA_DISTANCE
        if root is not None:
            raw = root.property("cameraDistance")
            if raw:
                distance = float(raw)
        viewport_h = max(1, self.height() - 86 - 230)
        frame = overseer_runtime.build_frame(
            units, distance, float(viewport_h), self._prev_lods
        )
        self._prev_lods = frame["prevLods"]
        if root is not None and hasattr(root, "applyFrame"):
            root.applyFrame(frame)
        self.apply_hud_counts(units)
        if root is not None:
            self._wire_hud(root)
            hud = overseer_runtime.build_hud(
                snap,
                group_by=str(root.property("swarmGroupBy") or "caste"),
                search=str(root.property("swarmSearch") or ""),
                collapsed=self._qml_list_prop(root, "collapsedGroups"),
                selected_id=str(root.property("selectedUnitId") or ""),
                log_filter=str(root.property("logFilter") or "all"),
                log_query=str(root.property("logQuery") or ""),
                camera_distance=distance,
            )
            if hasattr(root, "applyHud"):
                root.applyHud(hud)
        if self._entry_timer.isActive():
            self._particle_paths = overseer_runtime.particle_paths(
                units,
                width=float(max(1, self.width())),
                height=float(max(1, self.height())),
            )
        return frame

    def _poll_snapshot(self) -> None:
        target = sentinel_control.bridge_target()
        if target is None:
            return
        host, port, token = target
        try:
            snap = overseer_runtime.fetch_snapshot(host, port, token)
        except Exception:
            log.warning("Sentinels window: snapshot poll failed")
            return
        self.apply_snapshot(snap)

    def _entry_tick(self) -> None:
        scene = self._scene
        root = scene.rootObject() if scene is not None else None
        if root is None:
            return
        ms = float(root.property("entryMs") or 0)
        reduced = bool(root.property("reducedMotion"))
        reversing = bool(root.property("reversing"))
        tl = overseer_runtime.entry_timeline(ms, reduced=reduced, reversing=reversing)
        for key in ("edge", "fill", "reveal", "moteFlight"):
            root.setProperty(key, float(tl[key]))
        root.setProperty("inputLive", bool(tl["inputLive"]))
        flight = float(tl["moteFlight"])
        start = (max(8, self.width() - 46), 48)
        # Relative start is the design mote mapped into the inset.
        inset_start = (1210, 1046)
        x = inset_start[0] + (start[0] - inset_start[0]) * flight
        y = inset_start[1] + (start[1] - inset_start[1]) * flight
        self._close_mote.move(int(x), int(y))
        r = max(8.0, float(tl["moteRadius"]))
        self._close_mote.setFixedSize(int(r * 4), int(r * 4))
        paths = self._particle_paths
        if paths:
            rows = []
            for path in paths:
                px, py, vis = overseer_runtime.particle_position(path, ms)
                if vis <= 0:
                    continue
                rows.append({
                    "x": (px - self.width() / 2) / 80.0,
                    "y": 0.4,
                    "z": (self.height() / 2 - py) / 80.0,
                    "visible": vis,
                })
            if hasattr(root, "setParticles"):
                root.setParticles(rows)
        if not bool(root.property("entryPlaying")):
            if hasattr(root, "setParticles"):
                root.setParticles([])
            self._particle_paths = []
            self._entry_timer.stop()

    def start_sentinel(self) -> None:
        """Run the normal start path off the UI thread, then poll for the URL."""
        self.start_button.setEnabled(False)
        self.offline_label.setText("Starting Sentinel")
        threading.Thread(
            target=sentinel_control.start,
            name="arelis-sentinel-start",
            daemon=True,
        ).start()
        self._tries = 0
        self._poll.start()

    def _poll_tick(self) -> None:
        self._tries += 1
        if sentinel_control.overseer_url() or self._tries >= _POLL_TRIES:
            self._poll.stop()
            self.start_button.setEnabled(True)
            self.offline_label.setText("Sentinel offline")
            self.refresh()

    def _fade_owner(self) -> None:
        owner = self._owner
        if owner is None:
            return
        surface = getattr(owner, "_quick_surface", None)
        self.presence.open_window(reduced=_reduced_motion())
        self.presence.apply_to(surface)
        mote = getattr(owner, "sentinel_mote", None)
        if mote is not None:
            mote.hide()

    def _restore_presence(self, reason: str = "close") -> None:
        owner = self._owner
        surface = getattr(owner, "_quick_surface", None) if owner is not None else None
        self.presence.restore(reason, reduced=_reduced_motion())
        self.presence.apply_to(surface)
        mote = getattr(owner, "sentinel_mote", None) if owner is not None else None
        if mote is not None:
            mote.show()
            mote.reposition()

    def showEvent(self, event) -> None:
        self.apply_theme()
        self._sync_inset()
        self.refresh()
        self._fade_owner()
        super().showEvent(event)

    def closeEvent(self, event) -> None:
        scene = self._scene
        root = scene.rootObject() if scene is not None else None
        if root is not None and hasattr(root, "startExit"):
            root.startExit(_reduced_motion())
            self._entry_timer.start()
        self._snap_timer.stop()
        self._mask_timer.stop()
        if self.presence.open:
            self._restore_presence("close")
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        if not self._entry_timer.isActive():
            self._close_mote.move(max(8, self.width() - 46), 48)
        self._place_hud(self.width())
        self.apply_hud_mask()
        super().resizeEvent(event)


def teardown_sentinel_window(window) -> None:
    """Quit: restore presence, stop polling, unload the page, then close."""
    win = getattr(window, "sentinel_window", None)
    if win is None:
        return
    window.sentinel_window = None
    win._poll.stop()
    win._snap_timer.stop()
    win._mask_timer.stop()
    win._entry_timer.stop()
    win._restore_presence("quit")
    if win._view is not None:
        win._view.setUrl(QUrl("about:blank"))
    win.close()
    win.deleteLater()


def attach_sentinel_mote(window) -> SentinelMote | None:
    """Filament entry mote below the orbit. Safe to call more than once."""
    existing = getattr(window, "sentinel_mote", None)
    if existing is not None:
        existing.reposition()
        return existing
    mote = SentinelMote(window)
    window.sentinel_mote = mote
    return mote


def open_sentinel_window(window) -> SentinelWindow:
    """View -> Sentinels, or the entry mote. One window per main window."""
    win = getattr(window, "sentinel_window", None)
    if win is None:
        win = SentinelWindow(window)
        window.sentinel_window = win
    win.show()
    win.raise_()
    win.activateWindow()
    return win
