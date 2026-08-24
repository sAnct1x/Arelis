"""Live webcam preview instrument (QtMultimedia).

Preview + device pick + still snapshot. Soft-fails when QtMultimedia video
or cameras are missing — same stance as arelis.ui.audio for the mic.

Ask Arelis: snapshot then emit ask_arelis so the app submits an Identify look.
Optional snapshot_blocking() for the camera tool while the dock is live.

In the physics room, track/record map knuckles onto the same preview.
The camera tool stays snapshot-only. Pose is not ambient watching.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, Qt, QTimer, Signal
from PySide6.QtGui import QImage
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
from arelis.spatial import PREFERRED_CAMERA
from arelis.spatial.scene import REACH_DEFAULT, clamp_reach
from arelis.spatial.takes import prune_stills
from arelis.spatial.types import Hand
from arelis.spatial.video import PREVIEW_MAX_WIDTH, pick_live_format
from arelis.ui.panels.hand_preview import HandPreview
from arelis.ui.panels.world import make_reach_control
from arelis.ui.theme import METRICS

log = logging.getLogger(__name__)

try:
    from PySide6.QtMultimedia import (
        QCamera,
        QImageCapture,
        QMediaCaptureSession,
        QMediaDevices,
        QVideoFrame,
        QVideoSink,
    )

    CAMERA_MULTIMEDIA_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - depends on the PySide6 build
    log.warning("QtMultimedia camera unavailable: %s", exc)
    CAMERA_MULTIMEDIA_AVAILABLE = False
    QCamera = None  # type: ignore[misc, assignment]
    QImageCapture = None  # type: ignore[misc, assignment]
    QMediaCaptureSession = None  # type: ignore[misc, assignment]
    QMediaDevices = None  # type: ignore[misc, assignment]
    QVideoFrame = None  # type: ignore[misc, assignment]
    QVideoSink = None  # type: ignore[misc, assignment]


def _usable_camera_name(name: str) -> bool:
    text = (name or "").lower()
    if "brother" in text or "mfc-" in text:
        return False
    return True


def list_video_input_names() -> list[str]:
    if not CAMERA_MULTIMEDIA_AVAILABLE:
        return []
    return [
        d.description()
        for d in QMediaDevices.videoInputs()
        if not d.isNull() and _usable_camera_name(d.description())
    ]


def scale_qimage(image: QImage, max_width: int) -> QImage:
    """Shrink for preview / pose. Smooth, not nearest — aliasing made tips crawl."""
    if image.isNull() or image.width() <= max_width:
        return image
    height = max(1, round(image.height() * (max_width / image.width())))
    return image.scaled(
        max_width,
        height,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    h, w = rgb.shape[:2]
    cont = np.ascontiguousarray(rgb)
    image = QImage(cont.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return image.copy()


def video_frame_to_rgb(frame, max_width: int) -> tuple[np.ndarray | None, int, int]:
    """RGB at max_width. Prefer a mapped subsample — full toImage is the 5 Hz path."""
    if frame is None or not frame.isValid():
        return None, 0, 0
    src_w, src_h = int(frame.width()), int(frame.height())
    sampled = _sample_mapped_frame(frame, max_width)
    if sampled is not None:
        return sampled, src_w, src_h
    image = frame.toImage()
    if image.isNull():
        return None, src_w, src_h
    small = scale_qimage(image, max_width)
    rgb = qimage_to_rgb(small)
    return rgb, src_w, src_h


def _sample_mapped_frame(frame, max_width: int) -> np.ndarray | None:
    if QVideoFrame is None:
        return None
    try:
        fmt = frame.pixelFormat()
    except Exception:
        return None
    name = str(fmt)
    if not frame.map(QVideoFrame.MapMode.ReadOnly):
        return None
    try:
        w, h = int(frame.width()), int(frame.height())
        if w < 1 or h < 1:
            return None
        dest_w, dest_h = _fit(w, h, max_width)
        bits = None
        try:
            bits = frame.bits(0)
        except TypeError:
            bits = frame.bits()
        if bits is None:
            return None
        try:
            bpl = int(frame.bytesPerLine(0))
        except TypeError:
            bpl = int(frame.bytesPerLine())
        raw = bytes(bits) if not isinstance(bits, (bytes, bytearray, memoryview)) else bits
        buf = np.frombuffer(raw, dtype=np.uint8)
        if "NV12" in name:
            return _sample_nv12(buf, w, h, bpl, dest_w, dest_h)
        if "YUY" in name or "UYVY" in name:
            return _sample_yuyv(buf, w, h, bpl, dest_w, dest_h, uyvy="UYVY" in name)
        if any(tag in name for tag in ("ARGB", "BGRA", "RGBA", "ABGR", "XRGB", "BGRX", "RGBX")):
            return _sample_rgb32(buf, w, h, bpl, dest_w, dest_h, name)
        return None
    except Exception:
        return None
    finally:
        frame.unmap()


def _fit(w: int, h: int, max_width: int) -> tuple[int, int]:
    from arelis.spatial.video import fit_size

    return fit_size(w, h, max_width)


def _xs(src_w: int, dest_w: int) -> np.ndarray:
    return (np.arange(dest_w) * (src_w / dest_w)).astype(np.int32)


def _ys(src_h: int, dest_h: int) -> np.ndarray:
    return (np.arange(dest_h) * (src_h / dest_h)).astype(np.int32)


def _sample_nv12(
    buf: np.ndarray, w: int, h: int, bpl: int, dw: int, dh: int
) -> np.ndarray:
    y_plane = buf[: bpl * h].reshape(h, bpl)[:, :w]
    xs, ys = _xs(w, dw), _ys(h, dh)
    y = y_plane[ys][:, xs].astype(np.float32)
    # Approximate luma as grey RGB — enough for the landmarker; UV is optional.
    rgb = np.empty((dh, dw, 3), dtype=np.uint8)
    grey = np.clip(y, 0, 255).astype(np.uint8)
    rgb[:, :, 0] = grey
    rgb[:, :, 1] = grey
    rgb[:, :, 2] = grey
    return rgb


def _sample_yuyv(
    buf: np.ndarray, w: int, h: int, bpl: int, dw: int, dh: int, *, uyvy: bool
) -> np.ndarray:
    row = buf[: bpl * h].reshape(h, bpl)
    xs, ys = _xs(w, dw), _ys(h, dh)
    # YUYV: Y0 U Y1 V. Take Y at 2*x.
    y = row[ys][:, xs * 2 if not uyvy else xs * 2 + 1]
    rgb = np.empty((dh, dw, 3), dtype=np.uint8)
    rgb[:, :, 0] = y
    rgb[:, :, 1] = y
    rgb[:, :, 2] = y
    return rgb


def _sample_rgb32(
    buf: np.ndarray, w: int, h: int, bpl: int, dw: int, dh: int, name: str
) -> np.ndarray:
    packed = buf[: bpl * h].reshape(h, bpl)
    xs, ys = _xs(w, dw), _ys(h, dh)
    bgra = "BGRA" in name or "BGRX" in name
    out = np.empty((dh, dw, 3), dtype=np.uint8)
    for j, y in enumerate(ys):
        row = packed[y]
        for i, x in enumerate(xs):
            o = int(x) * 4
            if bgra:
                out[j, i, 0] = row[o + 2]
                out[j, i, 1] = row[o + 1]
                out[j, i, 2] = row[o]
            else:
                out[j, i, 0] = row[o]
                out[j, i, 1] = row[o + 1]
                out[j, i, 2] = row[o + 2]
    return out


def qimage_to_rgb(image: QImage) -> np.ndarray | None:
    if image.isNull():
        return None
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    w, h = converted.width(), converted.height()
    if w < 1 or h < 1:
        return None
    bpl = converted.bytesPerLine()
    ptr = converted.constBits()
    buf = np.frombuffer(ptr, dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    return buf[:, : w * 3].reshape(h, w, 3).copy()


def _format_rows(device) -> list[tuple[int, int, float, str, object]]:
    rows: list[tuple[int, int, float, str, object]] = []
    try:
        formats = device.videoFormats()
    except Exception:
        return rows
    for fmt in formats:
        try:
            res = fmt.resolution()
            fps = float(fmt.maxFrameRate())
            pix = str(fmt.pixelFormat())
        except Exception:
            continue
        rows.append((int(res.width()), int(res.height()), fps, pix, fmt))
    return rows


def _prefer_1080p(camera, device) -> None:
    """Ask for the fastest 1080p (MJPEG 30), not YUY2 1080p5."""
    if camera is None or device is None:
        return
    rows = _format_rows(device)
    if not rows:
        return
    picked = pick_live_format([(w, h, fps, pix) for w, h, fps, pix, _ in rows])
    if picked is None:
        return
    pw, ph, pfps, ppix = picked
    chosen = None
    for w, h, fps, pix, fmt in rows:
        if (w, h, fps, pix) == (pw, ph, pfps, ppix):
            chosen = fmt
            break
    if chosen is None:
        return
    try:
        camera.setCameraFormat(chosen)
        log.info("camera format %sx%s @ %.0f %s", pw, ph, pfps, ppix)
    except Exception:
        log.debug("setCameraFormat failed", exc_info=True)


def _match_video_device(hint: str):
    if not CAMERA_MULTIMEDIA_AVAILABLE:
        return None
    devices = [
        d
        for d in QMediaDevices.videoInputs()
        if not d.isNull() and _usable_camera_name(d.description())
    ]
    if not devices:
        return None
    needle = (hint or "").strip().lower()
    if needle:
        for device in devices:
            if needle in device.description().lower():
                return device
    for device in devices:
        if PREFERRED_CAMERA.lower() in device.description().lower():
            return device
    default = QMediaDevices.defaultVideoInput()
    if default is not None and not default.isNull() and _usable_camera_name(
        default.description()
    ):
        return default
    return devices[0]


class CameraPanel(QWidget):
    """Instrument body: pick a camera, preview, grab a still to outputs/images."""

    status = Signal(str)
    snapshot_saved = Signal(str)
    ask_arelis = Signal(str)
    running_changed = Signal(bool)
    pose_frame = Signal(object)
    pose_video = Signal(object, float)
    track_toggled = Signal(bool)
    record_toggled = Signal(bool)
    reach_changed = Signal(float)

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
        self._sink = None
        self._want_pose = False

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
        self.track_btn = QPushButton("track")
        self.record_btn = QPushButton("record")
        self.track_btn.setCheckable(True)
        self.record_btn.setCheckable(True)
        self.track_btn.setVisible(False)
        self.record_btn.setVisible(False)
        self.track_btn.setToolTip("Map knuckles on this preview. Physics room only.")
        self.record_btn.setToolTip("Write a take under outputs/physics/takes/.")
        for btn in (
            self.start_btn,
            self.stop_btn,
            self.snap_btn,
            self.ask_btn,
            self.track_btn,
            self.record_btn,
        ):
            btn.setObjectName("InstrumentAction")
            btn.setFixedHeight(METRICS["row"])
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.snap_btn.clicked.connect(self.snapshot)
        self.ask_btn.clicked.connect(self.ask)
        self.track_btn.toggled.connect(self._on_track_toggled)
        self.record_btn.toggled.connect(self._on_record_toggled)
        self.ask_btn.setToolTip(
            "One still, then Allow — Identify what is in frame. "
            "Typed chat can Read, Translate, or ask if food is still good."
        )

        row.addWidget(self.device_combo, stretch=1)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.snap_btn)
        row.addWidget(self.ask_btn)
        row.addWidget(self.track_btn)
        row.addWidget(self.record_btn)
        layout.addLayout(row)

        reach_row = QHBoxLayout()
        reach_row.setSpacing(8)
        self.reach_caption = QLabel("reach")
        self.reach_caption.setObjectName("InstrumentHint")
        self.reach_slider, self.reach_label = make_reach_control(self, REACH_DEFAULT)
        self.reach_slider.valueChanged.connect(self._on_reach_slider)
        reach_row.addWidget(self.reach_caption)
        reach_row.addWidget(self.reach_slider)
        reach_row.addWidget(self.reach_label)
        reach_row.addStretch(1)
        layout.addLayout(reach_row)
        for widget in (self.reach_caption, self.reach_slider, self.reach_label):
            widget.hide()

        self.hint = QLabel("")
        self.hint.setObjectName("InstrumentHint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        if CAMERA_MULTIMEDIA_AVAILABLE:
            self.video = HandPreview(self)
            layout.addWidget(self.video, stretch=1)
        else:
            self.video = QLabel("Camera preview unavailable in this PySide6 build.")
            self.video.setObjectName("InstrumentHint")
            self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video.setMinimumHeight(180)
            self.video.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
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
            elif self.device_combo.findData(PREFERRED_CAMERA) >= 0:
                self.device_combo.setCurrentIndex(
                    self.device_combo.findData(PREFERRED_CAMERA)
                )
        self.device_combo.blockSignals(False)

    def _sync_controls(self) -> None:
        ok = CAMERA_MULTIMEDIA_AVAILABLE and bool(list_video_input_names())
        self.start_btn.setEnabled(ok and not self._running)
        self.stop_btn.setEnabled(ok and self._running)
        self.snap_btn.setEnabled(ok and self._running)
        self.ask_btn.setEnabled(ok)
        self.track_btn.setEnabled(ok)
        self.record_btn.setEnabled(ok and self.track_btn.isChecked())
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
            _prefer_1080p(self._camera, device)
            self._image_capture = QImageCapture(self)
            self._session.setCamera(self._camera)
            self._session.setImageCapture(self._image_capture)
            if QVideoSink is not None:
                self._sink = QVideoSink(self)
                self._sink.videoFrameChanged.connect(self._on_video_frame)
                self._session.setVideoSink(self._sink)
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
        if self.track_btn.isChecked():
            self.track_btn.setChecked(False)

    def set_spatial_available(self, available: bool) -> None:
        """Show track/record only in the physics room."""
        self.track_btn.setVisible(available)
        self.record_btn.setVisible(available)
        for widget in (self.reach_caption, self.reach_slider, self.reach_label):
            widget.setVisible(available)
        if not available:
            if self.track_btn.isChecked():
                self.track_btn.setChecked(False)
            if self.record_btn.isChecked():
                self.record_btn.setChecked(False)

    def set_reach(self, reach: float) -> None:
        value = clamp_reach(reach)
        slider = round(value * 100)
        if self.reach_slider.value() != slider:
            self.reach_slider.blockSignals(True)
            self.reach_slider.setValue(slider)
            self.reach_slider.blockSignals(False)
        self.reach_label.setText(f"{value:.2f}x")

    def _on_reach_slider(self, raw: int) -> None:
        value = clamp_reach(raw / 100.0)
        self.reach_label.setText(f"{value:.2f}x")
        self.reach_changed.emit(value)

    def set_preview(self, image: QImage) -> None:
        if isinstance(self.video, HandPreview) and not image.isNull():
            self.video.set_frame(image)

    def set_hands(
        self,
        hands: tuple[Hand, ...],
        closed: bool = False,
        state: str = "",
        fps: float = 0.0,
        closed_kinds: dict[str, str] | None = None,
        closed_labels: frozenset[str] | set[str] | None = None,
    ) -> None:
        if isinstance(self.video, HandPreview):
            self.video.set_hands(
                hands,
                closed=closed,
                state=state,
                fps=fps,
                closed_kinds=closed_kinds,
                closed_labels=closed_labels,
            )

    def current_device_name(self) -> str:
        return str(self.device_combo.currentData() or "")

    def _on_track_toggled(self, checked: bool) -> None:
        self._want_pose = bool(checked)
        if not checked and isinstance(self.video, HandPreview):
            self.video.clear_hands()
        if not checked and self.record_btn.isChecked():
            self.record_btn.setChecked(False)
        self._sync_controls()
        self.track_toggled.emit(bool(checked))

    def _on_record_toggled(self, checked: bool) -> None:
        self.record_toggled.emit(bool(checked))

    def _on_video_frame(self, frame) -> None:
        if QVideoFrame is None or not frame.isValid():
            return
        if self._want_pose:
            # Convert off the UI thread. Preview comes back scaled from the worker.
            self.pose_video.emit(frame, time.perf_counter())
            return
        rgb, _, _ = video_frame_to_rgb(frame, PREVIEW_MAX_WIDTH)
        if rgb is None or not isinstance(self.video, HandPreview):
            return
        self.video.set_frame(rgb_to_qimage(rgb))

    def _teardown_camera(self) -> None:
        cam = self._camera
        sink = self._sink
        self._camera = None
        self._session = None
        self._image_capture = None
        self._sink = None
        self._pending_snapshot = None
        if sink is not None:
            try:
                sink.videoFrameChanged.disconnect(self._on_video_frame)
            except (TypeError, RuntimeError):
                pass
        if isinstance(self.video, HandPreview):
            self.video.clear_hands()
            self.video.set_frame(QImage())
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
        prune_stills(saved.parent)
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
