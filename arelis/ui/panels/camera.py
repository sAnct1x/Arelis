"""Live webcam preview instrument (QtMultimedia).

Preview + device pick + still snapshot. Soft-fails when QtMultimedia video
or cameras are missing — same stance as arelis.ui.audio for the mic.

Ask Arelis: snapshot then emit ask_arelis so the app submits an Identify look.
Optional snapshot_blocking() for the camera tool while the dock is live.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from arelis.core.failure_copy import plain_reason
from arelis.paths import outputs_dir
from arelis.ui.theme import METRICS

log = logging.getLogger(__name__)

try:
    from PySide6.QtMultimedia import (
        QCamera,
        QImageCapture,
        QMediaCaptureSession,
        QMediaDevices,
    )
    from PySide6.QtMultimediaWidgets import QVideoWidget

    CAMERA_MULTIMEDIA_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - depends on the PySide6 build
    log.warning("QtMultimedia camera unavailable: %s", exc)
    CAMERA_MULTIMEDIA_AVAILABLE = False
    QCamera = None  # type: ignore[misc, assignment]
    QImageCapture = None  # type: ignore[misc, assignment]
    QMediaCaptureSession = None  # type: ignore[misc, assignment]
    QMediaDevices = None  # type: ignore[misc, assignment]
    QVideoWidget = None  # type: ignore[misc, assignment]


def list_video_input_names() -> list[str]:
    if not CAMERA_MULTIMEDIA_AVAILABLE:
        return []
    return [d.description() for d in QMediaDevices.videoInputs() if not d.isNull()]


def _match_video_device(hint: str):
    if not CAMERA_MULTIMEDIA_AVAILABLE:
        return None
    devices = [d for d in QMediaDevices.videoInputs() if not d.isNull()]
    if not devices:
        return None
    needle = (hint or "").strip().lower()
    if needle:
        for device in devices:
            if needle in device.description().lower():
                return device
    default = QMediaDevices.defaultVideoInput()
    if default is not None and not default.isNull():
        return default
    return devices[0]


class CameraPanel(QWidget):
    """Instrument body: pick a camera, preview, grab a still to outputs/images."""

    status = Signal(str)
    snapshot_saved = Signal(str)
    ask_arelis = Signal(str)
    running_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._camera = None
        self._session = None
        self._image_capture = None
        self._running = False
        self._pending_snapshot: Path | None = None
        self._ask_after_next_save = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.device_combo = QComboBox()
        self.device_combo.setObjectName("InstrumentCombo")
        self.device_combo.setFixedHeight(METRICS["row"])
        self.device_combo.setMinimumWidth(140)
        self.device_combo.setToolTip("Camera device")
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)

        self.start_btn = QPushButton("start")
        self.stop_btn = QPushButton("stop")
        self.snap_btn = QPushButton("snapshot")
        self.ask_btn = QPushButton("ask Arelis")
        for btn in (self.start_btn, self.stop_btn, self.snap_btn, self.ask_btn):
            btn.setObjectName("InstrumentAction")
            btn.setFixedHeight(METRICS["row"])
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.snap_btn.clicked.connect(self.snapshot)
        self.ask_btn.clicked.connect(self.ask)
        self.ask_btn.setToolTip(
            "One still, then Allow — Identify what is in frame. "
            "Typed chat can Read, Translate, or ask if food is still good."
        )

        row.addWidget(self.device_combo, stretch=1)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.snap_btn)
        row.addWidget(self.ask_btn)
        layout.addLayout(row)

        self.hint = QLabel("")
        self.hint.setObjectName("InstrumentHint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        if CAMERA_MULTIMEDIA_AVAILABLE and QVideoWidget is not None:
            self.video = QVideoWidget(self)
            self.video.setMinimumHeight(180)
            self.video.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            layout.addWidget(self.video, stretch=1)
        else:
            self.video = QLabel("Camera preview unavailable in this PySide6 build.")
            self.video.setObjectName("InstrumentHint")
            self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video.setMinimumHeight(180)
            layout.addWidget(self.video, stretch=1)

        self._refresh_devices()
        self._sync_controls()
        if not CAMERA_MULTIMEDIA_AVAILABLE:
            self._set_hint("QtMultimedia camera support is not available.")

    def problem(self) -> str | None:
        if not CAMERA_MULTIMEDIA_AVAILABLE:
            return "QtMultimedia camera support is not available in this PySide6 build."
        if not list_video_input_names():
            return "No camera devices found."
        return None

    def _set_hint(self, text: str) -> None:
        self.hint.setText(text)
        self.status.emit(text)

    def _refresh_devices(self) -> None:
        self.device_combo.blockSignals(True)
        current = self.device_combo.currentData()
        self.device_combo.clear()
        names = list_video_input_names()
        if not names:
            self.device_combo.addItem("(no cameras)", "")
        else:
            for name in names:
                self.device_combo.addItem(name, name)
            if current:
                idx = self.device_combo.findData(current)
                if idx >= 0:
                    self.device_combo.setCurrentIndex(idx)
        self.device_combo.blockSignals(False)

    def _sync_controls(self) -> None:
        ok = CAMERA_MULTIMEDIA_AVAILABLE and bool(list_video_input_names())
        self.start_btn.setEnabled(ok and not self._running)
        self.stop_btn.setEnabled(ok and self._running)
        self.snap_btn.setEnabled(ok and self._running)
        self.ask_btn.setEnabled(ok)
        self.device_combo.setEnabled(ok)

    def _on_device_changed(self, _index: int = 0) -> None:
        if self._running:
            self.stop()
            self.start()

    def start(self) -> None:
        problem = self.problem()
        if problem:
            self._set_hint(problem)
            self._sync_controls()
            return
        if self._running:
            return
        device = _match_video_device(str(self.device_combo.currentData() or ""))
        if device is None:
            self._set_hint("No camera devices found.")
            self._sync_controls()
            return
        try:
            self._session = QMediaCaptureSession(self)
            self._camera = QCamera(device, self)
            self._image_capture = QImageCapture(self)
            self._session.setCamera(self._camera)
            self._session.setVideoOutput(self.video)
            self._session.setImageCapture(self._image_capture)
            self._image_capture.imageSaved.connect(self._on_image_saved)
            self._image_capture.errorOccurred.connect(self._on_capture_error)
            self._camera.errorOccurred.connect(self._on_camera_error)
            self._camera.start()
            self._running = True
            self._set_hint(f"Live: {device.description()}")
            self.running_changed.emit(True)
        except Exception as exc:
            log.warning("camera start failed: %s", exc, exc_info=True)
            self._teardown_camera()
            self._set_hint(f"The camera would not start. {plain_reason(exc)}")
        self._sync_controls()

    def stop(self) -> None:
        if not self._running and self._camera is None:
            self._sync_controls()
            return
        self._teardown_camera()
        was_running = self._running
        self._running = False
        self._ask_after_next_save = False
        self._set_hint("Camera stopped.")
        self._sync_controls()
        if was_running:
            self.running_changed.emit(False)

    def _teardown_camera(self) -> None:
        cam = self._camera
        self._camera = None
        self._session = None
        self._image_capture = None
        self._pending_snapshot = None
        if cam is None:
            return
        try:
            cam.stop()
        except Exception:
            log.debug("camera stop raised", exc_info=True)
        try:
            cam.deleteLater()
        except Exception:
            pass

    def snapshot(self) -> None:
        if not self._running or self._image_capture is None:
            self._set_hint("Start the camera before taking a snapshot.")
            return
        if not self._image_capture.isReadyForCapture():
            self._set_hint("Camera not ready for capture yet — wait a moment.")
            return
        out_dir = outputs_dir() / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = out_dir / f"camera_{stamp}.jpg"
        self._pending_snapshot = dest
        try:
            self._image_capture.captureToFile(str(dest))
            self._set_hint(f"Capturing… {dest.name}")
        except Exception as exc:
            self._pending_snapshot = None
            self._set_hint(f"The snapshot did not save. {plain_reason(exc)}")

    def ask(self) -> None:
        """Ensure preview is live, snapshot, then ask Arelis on the saved frame."""
        self._ask_after_next_save = True
        if not self._running:
            self.start()
        if not self._running:
            self._ask_after_next_save = False
            return
        self.snapshot()
        if self._pending_snapshot is None and self._ask_after_next_save:
            # snapshot() failed immediately (not ready); clear the flag.
            self._ask_after_next_save = False

    def snapshot_blocking(self, timeout_ms: int = 8000) -> str | None:
        """Capture one frame and return the saved path, or None on timeout/fail.

        Used by the camera tool while the dock owns the live session. Must be
        called from the Qt GUI thread.
        """
        if not self._running:
            self.start()
        if not self._running or self._image_capture is None:
            return None
        loop = QEventLoop()
        result: list[str] = []

        def _on_saved(path: str) -> None:
            result.append(path)
            loop.quit()

        def _on_error(_id: int, _error, _msg: str) -> None:
            loop.quit()

        self.snapshot_saved.connect(_on_saved)
        if self._image_capture is not None:
            self._image_capture.errorOccurred.connect(_on_error)
        QTimer.singleShot(max(500, int(timeout_ms)), loop.quit)
        self.snapshot()
        if self._pending_snapshot is None and not result:
            try:
                self.snapshot_saved.disconnect(_on_saved)
            except (TypeError, RuntimeError):
                pass
            return None
        loop.exec()
        try:
            self.snapshot_saved.disconnect(_on_saved)
        except (TypeError, RuntimeError):
            pass
        try:
            if self._image_capture is not None:
                self._image_capture.errorOccurred.disconnect(_on_error)
        except (TypeError, RuntimeError):
            pass
        return result[0] if result else None

    def _on_image_saved(self, _id: int, path: str) -> None:
        saved = Path(path)
        self._pending_snapshot = None
        self._set_hint(f"Saved {saved}")
        self.snapshot_saved.emit(str(saved))
        if self._ask_after_next_save:
            self._ask_after_next_save = False
            self.ask_arelis.emit(str(saved))

    def _on_capture_error(self, _id: int, _error, error_string: str) -> None:
        self._pending_snapshot = None
        self._ask_after_next_save = False
        self._set_hint(f"Snapshot failed: {error_string}")

    def _on_camera_error(self, _error, error_string: str) -> None:
        self._teardown_camera()
        was_running = self._running
        self._running = False
        self._ask_after_next_save = False
        self._set_hint(f"Camera error: {error_string}")
        self._sync_controls()
        if was_running:
            self.running_changed.emit(False)
