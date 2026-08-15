"""Single Settings dialog — Audio, Window, Notify, Roots, Memory (glass panel)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSlider,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.core.failure_copy import plain_reason
from arelis.notify.center import CHANNELS, load_channels
from arelis.sms_ingest import format_ingest_listen_urls
from arelis.ui.audio import list_audio_input_names, list_audio_output_names
from arelis.ui.glass import GlassFrame, advance_rim_pulse
from arelis.ui.icons import window_close_icon
from arelis.ui.panels.memory import ActiveFactsPanel
from arelis.ui.theme import GLASS


class SettingsDialog(QDialog):
    """Frameless glass settings surface. Emits applied when the user accepts.

    Memory forget commits immediately via fact_decided (not batched with Apply).
    """

    applied = Signal(dict)
    fact_decided = Signal(object, str)

    def __init__(
        self,
        config: dict[str, Any],
        *,
        always_on_top: bool = False,
        chat_font_scale: float = 1.0,
        active_facts: list[dict[str, object]] | None = None,
        parent: QWidget | None = None,
        on_test_mic: Callable[[], str] | None = None,
        on_test_speak: Callable[[], None] | None = None,
        on_reset_layout: Callable[[], None] | None = None,
        initial_tab: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(520, 560)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._on_test_mic = on_test_mic
        self._on_test_speak = on_test_speak
        self._on_reset_layout = on_reset_layout
        self._drag_origin: QPoint | None = None
        self._rim_pulse = QTimer(self)
        self._rim_pulse.setInterval(100)
        self._rim_pulse.timeout.connect(self._tick_rim_pulse)
        self._roots: list[dict[str, Any]] = self._load_roots(config)

        voice = config.get("voice") or {}
        stt = voice.get("stt") or {}
        tts = voice.get("tts") or {}
        presence = config.get("presence") or {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Smoked settings plate — readable over the void, not a holographic TV.
        panel = GlassFrame(
            self,
            object_name="SettingsGlass",
            fill_alpha=int(GLASS.get("fill_settings", 200)),
            radius=float(GLASS.get("radius", 16.0)),
            pulse_rim=False,
        )
        outer.addWidget(panel)

        root = QVBoxLayout(panel)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        heading = QLabel("Settings")
        heading.setObjectName("SettingsHeading")
        heading.setCursor(Qt.CursorShape.OpenHandCursor)
        heading.setToolTip("Drag to move")
        heading.installEventFilter(self)
        head.addWidget(heading, stretch=1)
        close_btn = QToolButton()
        close_btn.setObjectName("SettingsClose")
        close_btn.setIcon(window_close_icon(12))
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self.reject)
        head.addWidget(close_btn)
        root.addLayout(head)

        tabs = QTabWidget()
        tabs.setObjectName("SettingsTabs")
        tabs.setDocumentMode(True)
        tabs.setUsesScrollButtons(False)
        root.addWidget(tabs, stretch=1)

        # --- Audio ---
        audio = QWidget()
        audio.setObjectName("SettingsTabBody")
        audio_form = QFormLayout(audio)
        audio_form.setContentsMargins(14, 16, 14, 12)
        audio_form.setSpacing(12)
        audio_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        audio_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.mic_combo = QComboBox()
        self.mic_combo.setObjectName("SettingsField")
        self.mic_combo.addItem("System default", "")
        for name in list_audio_input_names():
            self.mic_combo.addItem(name, name)
        self._select_by_data(self.mic_combo, str(voice.get("input_device") or ""))

        self.speaker_combo = QComboBox()
        self.speaker_combo.setObjectName("SettingsField")
        self.speaker_combo.addItem("System default", "")
        for name in list_audio_output_names():
            self.speaker_combo.addItem(name, name)
        self._select_by_data(self.speaker_combo, str(voice.get("output_device") or ""))

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("SettingsSlider")
        self.volume_slider.setRange(0, 100)
        vol = float(voice.get("output_volume", 1.0))
        self.volume_slider.setValue(int(max(0.0, min(1.0, vol)) * 100))
        self.volume_label = QLabel(f"{self.volume_slider.value()}%")
        self.volume_label.setObjectName("SettingsHint")
        self.volume_slider.valueChanged.connect(
            lambda v: self.volume_label.setText(f"{v}%")
        )
        vol_row = QHBoxLayout()
        vol_row.addWidget(self.volume_slider, stretch=1)
        vol_row.addWidget(self.volume_label)

        self.voice_enabled = QCheckBox("Voice features")
        self.voice_enabled.setChecked(bool(voice.get("enabled", True)))
        self.stt_enabled = QCheckBox("Listen (speech to text)")
        self.stt_enabled.setChecked(bool(stt.get("enabled", True)))
        self.tts_enabled = QCheckBox("Speak (text to speech)")
        self.tts_enabled.setChecked(bool(tts.get("enabled", True)))

        test_row = QHBoxLayout()
        self.test_mic_btn = QPushButton("Test mic")
        self.test_speak_btn = QPushButton("Test speak")
        self.test_status = QLabel("")
        self.test_status.setObjectName("SettingsHint")
        self.test_status.setWordWrap(True)
        self.test_mic_btn.clicked.connect(self._run_test_mic)
        self.test_speak_btn.clicked.connect(self._run_test_speak)
        test_row.addWidget(self.test_mic_btn)
        test_row.addWidget(self.test_speak_btn)
        test_row.addStretch(1)

        audio_form.addRow("Microphone", self.mic_combo)
        audio_form.addRow("Speaker", self.speaker_combo)
        audio_form.addRow("Volume", vol_row)
        audio_form.addRow(self.voice_enabled)
        audio_form.addRow(self.stt_enabled)
        audio_form.addRow(self.tts_enabled)
        audio_form.addRow(test_row)
        audio_form.addRow(self.test_status)
        tabs.addTab(audio, "Audio")

        # --- Window ---
        window = QWidget()
        window.setObjectName("SettingsTabBody")
        win_form = QFormLayout(window)
        win_form.setContentsMargins(14, 16, 14, 12)
        win_form.setSpacing(12)
        win_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        win_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.always_on_top = QCheckBox("Always on top")
        self.always_on_top.setChecked(always_on_top)
        self.close_to_tray = QCheckBox("Close to tray")
        self.close_to_tray.setChecked(bool(presence.get("close_to_tray", True)))
        self.close_to_tray.setToolTip(
            "Closing the window leaves Arelis in the tray so inbound Notify keeps working."
        )

        self.font_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_slider.setObjectName("SettingsSlider")
        self.font_slider.setRange(75, 175)
        self.font_slider.setSingleStep(5)
        self.font_slider.setValue(round(chat_font_scale * 100))
        self.font_label = QLabel(f"{self.font_slider.value()}%")
        self.font_label.setObjectName("SettingsHint")
        self.font_slider.valueChanged.connect(
            lambda v: self.font_label.setText(f"{v}%")
        )
        font_row = QHBoxLayout()
        font_row.addWidget(self.font_slider, stretch=1)
        font_row.addWidget(self.font_label)

        self.reset_layout_btn = QPushButton("Reset layout")
        self.reset_layout_btn.setToolTip("Conversation glass only; docks closed.")
        self.reset_layout_btn.clicked.connect(self._run_reset_layout)

        win_form.addRow(self.always_on_top)
        win_form.addRow(self.close_to_tray)
        win_form.addRow("Chat text size", font_row)
        win_form.addRow(self.reset_layout_btn)
        tabs.addTab(window, "Window")

        # --- Notify ---
        notify = QWidget()
        notify.setObjectName("SettingsTabBody")
        notify_l = QVBoxLayout(notify)
        notify_l.setContentsMargins(14, 16, 14, 12)
        notify_l.setSpacing(12)
        channels_blurb = QLabel(
            "Live pill while Arelis is open. Voice cues only when idle, "
            "and never during a turn. Same bits later for "
            "“stop telling me about calendar events.”"
        )
        channels_blurb.setObjectName("SettingsHint")
        channels_blurb.setWordWrap(True)
        notify_l.addWidget(channels_blurb)
        channel_form = QFormLayout()
        channel_form.setSpacing(8)
        channel_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        labels = {
            "sms": "SMS",
            "calendar": "Calendar",
            "email": "Email (contacts)",
            "job": "Long jobs",
            "task": "Tasks",
            "allow": "Allow",
        }
        current = load_channels(config)
        self._notify_channels: dict[str, QComboBox] = {}
        for key in CHANNELS:
            combo = QComboBox()
            combo.setObjectName("SettingsField")
            combo.addItem("Off", "off")
            combo.addItem("Visual", "visual")
            combo.addItem("Visual + voice", "voice")
            self._select_by_data(combo, current.get(key, "visual"))
            channel_form.addRow(labels.get(key, key), combo)
            self._notify_channels[key] = combo
        notify_l.addLayout(channel_form)

        phone_blurb = QLabel(
            "Phone ingest URL for the Android companion on the same Wi-Fi. "
            "Keep Arelis running (tray is OK)."
        )
        phone_blurb.setObjectName("SettingsHint")
        phone_blurb.setWordWrap(True)
        self.notify_url = QLabel(self._notify_url_text(config))
        self.notify_url.setObjectName("SettingsNotifyUrl")
        self.notify_url.setWordWrap(True)
        self.notify_url.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        copy_btn = QPushButton("Copy primary URL")
        copy_btn.clicked.connect(lambda: self._copy_notify_url(config))
        notify_l.addWidget(phone_blurb)
        notify_l.addWidget(self.notify_url)
        notify_l.addWidget(copy_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        notify_l.addStretch(1)
        tabs.addTab(notify, "Notify")

        # --- Roots (projects Arelis may read/write) ---
        roots_tab = QWidget()
        roots_tab.setObjectName("SettingsTabBody")
        roots_l = QVBoxLayout(roots_tab)
        roots_l.setContentsMargins(14, 16, 14, 12)
        roots_l.setSpacing(10)
        roots_hint = QLabel(
            "Folders Arelis may read and write. Default is this repo only. "
            "Add another project when you actually work on it — workspace dock "
            "(add / new / remove) or edit here. Writes need Allow; read-only "
            "roots never accept write/edit. Saved to data/config.local.yaml."
        )
        roots_hint.setObjectName("SettingsHint")
        roots_hint.setWordWrap(True)
        roots_l.addWidget(roots_hint)

        self.roots_list = QListWidget()
        self.roots_list.setObjectName("SettingsField")
        self.roots_list.currentRowChanged.connect(self._on_root_selected)
        roots_l.addWidget(self.roots_list, stretch=1)

        root_form = QFormLayout()
        root_form.setSpacing(8)
        self.root_name = QLineEdit()
        self.root_name.setObjectName("SettingsField")
        self.root_name.setPlaceholderText("arelis")
        path_row = QHBoxLayout()
        self.root_path = QLineEdit()
        self.root_path.setObjectName("SettingsField")
        self.root_path.setPlaceholderText("C:/Users/…/project")
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_root_path)
        path_row.addWidget(self.root_path, stretch=1)
        path_row.addWidget(browse_btn)
        self.root_read_only = QCheckBox("Read-only")
        root_form.addRow("Name", self.root_name)
        root_form.addRow("Path", path_row)
        root_form.addRow(self.root_read_only)
        roots_l.addLayout(root_form)

        root_btns = QHBoxLayout()
        add_btn = QPushButton("Add")
        update_btn = QPushButton("Update")
        remove_btn = QPushButton("Remove")
        add_btn.clicked.connect(self._add_root)
        update_btn.clicked.connect(self._update_root)
        remove_btn.clicked.connect(self._remove_root)
        root_btns.addWidget(add_btn)
        root_btns.addWidget(update_btn)
        root_btns.addWidget(remove_btn)
        root_btns.addStretch(1)
        roots_l.addLayout(root_btns)
        self._refresh_roots_list()
        tabs.addTab(roots_tab, "Roots")

        # --- Memory (live: forget commits immediately, not via Apply) ---
        self.memory = ActiveFactsPanel()
        self.memory.setObjectName("SettingsTabBody")
        self.memory.fact_decided.connect(self.fact_decided.emit)
        self.memory.set_facts(list(active_facts or []))
        tabs.addTab(self.memory, "Memory")
        self.tabs = tabs
        want = (initial_tab or "").strip().lower()
        if want:
            for i in range(tabs.count()):
                if tabs.tabText(i).lower() == want:
                    tabs.setCurrentIndex(i)
                    break

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("SettingsButtons")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._rim_pulse.start()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._rim_pulse.stop()
        super().hideEvent(event)

    def _tick_rim_pulse(self) -> None:
        advance_rim_pulse(0.1)
        for frame in self.findChildren(GlassFrame):
            frame.update()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        """Drag the frameless glass by the Settings heading."""
        name = obj.objectName() if hasattr(obj, "objectName") else ""
        if name == "SettingsHeading" and isinstance(event, QMouseEvent):
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._drag_origin = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                return True
            if (
                event.type() == QEvent.Type.MouseMove
                and self._drag_origin is not None
                and bool(event.buttons() & Qt.MouseButton.LeftButton)
            ):
                self.move(event.globalPosition().toPoint() - self._drag_origin)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_origin = None
                return True
        return super().eventFilter(obj, event)

    def set_active_facts(self, facts: list[dict[str, object]]) -> None:
        """Refresh the Memory tab after a live forget (or external store change)."""
        self.memory.set_facts(facts)

    @staticmethod
    def _select_by_data(combo: QComboBox, value: str) -> None:
        if not value:
            combo.setCurrentIndex(0)
            return
        needle = value.strip().lower()
        for i in range(combo.count()):
            data = str(combo.itemData(i) or "")
            if data and needle in data.lower():
                combo.setCurrentIndex(i)
                return
            if data and data.lower() == needle:
                combo.setCurrentIndex(i)
                return
        # Persist a custom hint even if the device is unplugged.
        combo.addItem(value, value)
        combo.setCurrentIndex(combo.count() - 1)

    @staticmethod
    def _notify_urls(config: dict[str, Any]) -> tuple[str, str]:
        sms_cfg = (config.get("tools") or {}).get("sms") or {}
        inbound = sms_cfg.get("inbound") or {}
        ingest = inbound.get("ingest") or {}
        port = int(ingest.get("port") or 8765)
        host = str(ingest.get("host") or "0.0.0.0")
        urls = format_ingest_listen_urls(port, host=host)
        primary = urls.split(",")[0].strip() if urls else urls
        return urls, primary

    def _notify_url_text(self, config: dict[str, Any]) -> str:
        urls, _ = self._notify_urls(config)
        return urls or "(no listen address)"

    def _copy_notify_url(self, config: dict[str, Any]) -> None:
        _, primary = self._notify_urls(config)
        if not primary:
            return
        clip = QApplication.clipboard()
        if clip is not None:
            clip.setText(primary)
        self.test_status.setText(f"Copied: {primary}")

    def _run_test_mic(self) -> None:
        if self._on_test_mic is None:
            self.test_status.setText("Microphone test unavailable.")
            return
        try:
            msg = self._on_test_mic() or "Microphone OK."
        except Exception as exc:
            msg = f"The microphone test did not run. {plain_reason(exc)}"
        self.test_status.setText(msg)

    def _run_test_speak(self) -> None:
        if self._on_test_speak is None:
            self.test_status.setText("Speak test unavailable.")
            return
        try:
            self._on_test_speak()
            self.test_status.setText("Speaking a short test…")
        except Exception as exc:
            self.test_status.setText(
                f"The speech test did not run. {plain_reason(exc)}"
            )

    def _run_reset_layout(self) -> None:
        if self._on_reset_layout is not None:
            self._on_reset_layout()
            self.test_status.setText("Layout reset.")

    @staticmethod
    def _load_roots(config: dict[str, Any]) -> list[dict[str, Any]]:
        workspace = config.get("workspace") or {}
        named = workspace.get("named_roots")
        if isinstance(named, list) and named:
            out: list[dict[str, Any]] = []
            for item in named:
                if not isinstance(item, dict):
                    continue
                out.append(
                    {
                        "name": str(item.get("name") or "").strip(),
                        "path": str(item.get("path") or "").strip(),
                        "read_only": bool(item.get("read_only", False)),
                    }
                )
            return out
        flat = workspace.get("roots") or ["."]
        loaded: list[dict[str, Any]] = []
        for item in flat:
            if isinstance(item, dict):
                loaded.append(
                    {
                        "name": str(item.get("name") or Path(str(item.get("path") or ".")).name),
                        "path": str(item.get("path") or ".").strip(),
                        "read_only": bool(item.get("read_only", False)),
                    }
                )
            else:
                p = str(item)
                loaded.append(
                    {"name": Path(p).name or "root", "path": p, "read_only": False}
                )
        return loaded or [{"name": "root", "path": ".", "read_only": False}]

    def _root_label(self, entry: dict[str, Any]) -> str:
        ro = " [read-only]" if entry.get("read_only") else ""
        return f"{entry.get('name') or '?'} — {entry.get('path') or '?'}{ro}"

    def _refresh_roots_list(self) -> None:
        self.roots_list.blockSignals(True)
        self.roots_list.clear()
        for entry in self._roots:
            self.roots_list.addItem(self._root_label(entry))
        self.roots_list.blockSignals(False)

    def _on_root_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._roots):
            return
        entry = self._roots[row]
        self.root_name.setText(str(entry.get("name") or ""))
        self.root_path.setText(str(entry.get("path") or ""))
        self.root_read_only.setChecked(bool(entry.get("read_only")))

    def _browse_root_path(self) -> None:
        start = self.root_path.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Workspace root folder", start)
        if chosen:
            self.root_path.setText(chosen)

    def _draft_root(self) -> dict[str, Any] | None:
        name = self.root_name.text().strip()
        path = self.root_path.text().strip()
        if not name or not path:
            self.test_status.setText("Root needs a name and a path.")
            return None
        return {
            "name": name,
            "path": path,
            "read_only": self.root_read_only.isChecked(),
        }

    def _add_root(self) -> None:
        entry = self._draft_root()
        if entry is None:
            return
        if any(r["name"] == entry["name"] for r in self._roots):
            self.test_status.setText(f"Root name `{entry['name']}` already exists.")
            return
        self._roots.append(entry)
        self._refresh_roots_list()
        self.roots_list.setCurrentRow(len(self._roots) - 1)
        self.test_status.setText(f"Added root `{entry['name']}`.")

    def _update_root(self) -> None:
        row = self.roots_list.currentRow()
        if row < 0 or row >= len(self._roots):
            self.test_status.setText("Select a root to update.")
            return
        entry = self._draft_root()
        if entry is None:
            return
        for i, other in enumerate(self._roots):
            if i != row and other["name"] == entry["name"]:
                self.test_status.setText(f"Root name `{entry['name']}` already exists.")
                return
        self._roots[row] = entry
        self._refresh_roots_list()
        self.roots_list.setCurrentRow(row)
        self.test_status.setText(f"Updated root `{entry['name']}`.")

    def _remove_root(self) -> None:
        row = self.roots_list.currentRow()
        if row < 0 or row >= len(self._roots):
            self.test_status.setText("Select a root to remove.")
            return
        if len(self._roots) <= 1:
            self.test_status.setText("Keep at least one workspace root.")
            return
        removed = self._roots.pop(row)
        self._refresh_roots_list()
        self.root_name.clear()
        self.root_path.clear()
        self.root_read_only.setChecked(False)
        self.test_status.setText(f"Removed root `{removed.get('name')}`.")

    def values(self) -> dict[str, Any]:
        return {
            "voice": {
                "enabled": self.voice_enabled.isChecked(),
                "input_device": str(self.mic_combo.currentData() or ""),
                "output_device": str(self.speaker_combo.currentData() or ""),
                "output_volume": self.volume_slider.value() / 100.0,
                "stt": {"enabled": self.stt_enabled.isChecked()},
                "tts": {"enabled": self.tts_enabled.isChecked()},
            },
            "presence": {
                "close_to_tray": self.close_to_tray.isChecked(),
            },
            "ui_prefs": {
                "always_on_top": self.always_on_top.isChecked(),
                "chat_font_scale": self.font_slider.value() / 100.0,
            },
            "workspace": {
                "roots": [
                    {
                        "name": str(r["name"]),
                        "path": str(r["path"]),
                        "read_only": bool(r.get("read_only", False)),
                    }
                    for r in self._roots
                ]
            },
            "ui": {
                "notifications": {
                    "channels": {
                        key: str(combo.currentData() or "visual")
                        for key, combo in self._notify_channels.items()
                    }
                }
            },
        }

    def _accept(self) -> None:
        self.applied.emit(self.values())
        self.accept()
