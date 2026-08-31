"""Physics-room hand tracking: worker + grant. Not a turn."""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from arelis.spatial import hands_log
from arelis.spatial.backend import PoseBackend, StubBackend, load_backend
from arelis.spatial.gesture import GestureMachine
from arelis.spatial.grant import grant_for, must_revoke
from arelis.spatial.takes import TakeWriter
from arelis.spatial.types import FilterBank, HandsFrame
from arelis.spatial.video import POSE_MAX_WIDTH

log = logging.getLogger(__name__)


class PoseWorker(QThread):
    """Latest-frame-only. Drops stale frames instead of queueing a backlog."""

    hands_ready = Signal(object)
    preview_ready = Signal(object)
    status = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._latest: tuple[Any, ...] | None = None
        self._new = threading.Event()
        self._stop = threading.Event()
        self._backend: PoseBackend | None = None
        self._filters = FilterBank()
        self._emit_preview = True

    def set_emit_preview(self, on: bool) -> None:
        self._emit_preview = bool(on)

    def submit(self, rgb: np.ndarray, t_capture: float, width: int, height: int) -> None:
        with self._lock:
            self._latest = ("rgb", rgb, t_capture, width, height)
        self._new.set()

    def submit_video(self, frame: object, t_capture: float) -> None:
        with self._lock:
            self._latest = ("video", frame, t_capture)
        self._new.set()

    def stop_worker(self) -> None:
        self._stop.set()
        self._new.set()

    def run(self) -> None:
        self._backend = load_backend()
        if isinstance(self._backend, StubBackend):
            self.status.emit(
                "Hands need MediaPipe. In this checkout: pip install -e \".[spatial]\""
            )
        else:
            self.status.emit(f"Hands: {self._backend.name}")
        try:
            while not self._stop.is_set():
                self._new.wait(timeout=0.25)
                self._new.clear()
                if self._stop.is_set():
                    break
                with self._lock:
                    item = self._latest
                    self._latest = None
                if item is None:
                    continue
                try:
                    rgb, t_cap, w, h = self._unpack(item)
                    if rgb is None:
                        continue
                    raw = self._backend.infer(rgb, t_cap, w, h)
                    framed = self._filters.apply(raw)
                except Exception as exc:
                    log.warning("pose infer failed: %s", exc)
                    continue
                self.hands_ready.emit(framed)
        finally:
            if self._backend is not None:
                self._backend.close()
            self._filters.reset()

    def _unpack(
        self, item: tuple[Any, ...]
    ) -> tuple[np.ndarray | None, float, int, int]:
        kind = item[0]
        if kind == "rgb":
            _, rgb, t_cap, w, h = item
            return rgb, float(t_cap), int(w), int(h)
        if kind == "video":
            _, frame, t_cap = item
            from arelis.ui.panels.camera import rgb_to_qimage, video_frame_to_rgb

            rgb, src_w, src_h = video_frame_to_rgb(frame, POSE_MAX_WIDTH)
            if rgb is None:
                return None, float(t_cap), 0, 0
            if self._emit_preview:
                self.preview_ready.emit(rgb_to_qimage(rgb))
            return rgb, float(t_cap), src_w, src_h
        return None, 0.0, 0, 0


class SpatialHands(QObject):
    """Owns the grant, the worker, and the take. Window wires the camera."""

    frame_ready = Signal(object)
    preview_ready = Signal(object)
    hint = Signal(str)
    tracking_changed = Signal(bool)
    recording_changed = Signal(bool)
    clicked = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._room_id = ""
        self._filament = False
        self._chip = False
        self._preview_wanted = False
        self._tracking = False
        self._parked = False
        self._worker: PoseWorker | None = None
        self._gesture = GestureMachine()
        self._take: TakeWriter | None = None
        self._intervals: deque[float] = deque(maxlen=45)
        self._last_t: float | None = None
        self._wrist_hist: deque[tuple[float, float]] = deque(maxlen=30)
        self._last_frame: HandsFrame | None = None
        self.last_state = "idle"
        self.last_fps = 0.0
        self.last_hand = None
        self.last_tracks = ()
        self.last_clicks = ()
        self.scene_log: Callable[[], dict[str, Any]] | None = None

    @property
    def tracking(self) -> bool:
        return self._tracking

    @property
    def recording(self) -> bool:
        return self._take is not None

    @property
    def allowed(self) -> bool:
        return grant_for(
            self._room_id,
            self._tracking,
            filament=self._filament,
            chip=self._chip,
        ).allowed

    @property
    def preview_wanted(self) -> bool:
        return self._preview_wanted

    def set_face(self, *, filament: bool, chip: bool) -> None:
        self._filament = bool(filament)
        self._chip = bool(chip)
        if must_revoke(
            self._room_id, filament=self._filament, chip=self._chip
        ):
            self.stop_track()

    def set_preview_wanted(self, on: bool) -> None:
        self._preview_wanted = bool(on)
        if self._worker is not None:
            self._worker.set_emit_preview(self._preview_wanted)

    def set_room(self, room_id: str) -> None:
        self._room_id = str(room_id or "")
        if must_revoke(
            self._room_id, filament=self._filament, chip=self._chip
        ):
            self.stop_track()

    def start_track(self, meta: dict[str, Any] | None = None) -> bool:
        if must_revoke(
            self._room_id, filament=self._filament, chip=self._chip
        ):
            self.hint.emit(
                "Hands need Reality Track, or the filament Hands chip."
            )
            return False
        if self._tracking:
            return True
        self._parked = False
        self._tracking = True
        self._gesture.reset()
        self._intervals.clear()
        self._wrist_hist.clear()
        self._last_t = None
        self._worker = PoseWorker(self)
        self._worker.set_emit_preview(self._preview_wanted)
        self._worker.hands_ready.connect(self._on_hands)
        self._worker.preview_ready.connect(self.preview_ready.emit)
        self._worker.status.connect(self.hint.emit)
        self._worker.start()
        self.tracking_changed.emit(True)
        device = (meta or {}).get("device", "")
        self.hint.emit(f"Tracking on{': ' + device if device else ''}.")
        hands_log.emit(
            "session_start",
            room=self._room_id,
            filament=self._filament,
            chip=self._chip,
            preview=self._preview_wanted,
            device=str(device or ""),
        )
        return True

    def stop_track(self) -> None:
        self.stop_record()
        was = self._tracking
        self._tracking = False
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.stop_worker()
            worker.wait(2000)
            worker.deleteLater()
        self._last_frame = None
        self.last_clicks = ()
        self.last_tracks = ()
        self.last_hand = None
        self.last_state = "idle"
        self.frame_ready.emit(None)
        if was:
            self.tracking_changed.emit(False)
            self.hint.emit("Tracking off.")
            hands_log.emit(
                "session_stop",
                room=self._room_id,
                filament=self._filament,
                chip=self._chip,
                parked=self._parked,
            )

    def park_session(self) -> None:
        """Rest / minimize: tear the camera down. Chip can bring it back."""
        if not self._tracking:
            return
        self._parked = True
        self.stop_track()

    def resume_if_parked(self, meta: dict[str, Any] | None = None) -> bool:
        if not self._parked:
            return False
        self._parked = False
        return self.start_track(meta)

    def start_record(self, extra_meta: dict[str, Any] | None = None) -> Path | None:
        if not self.allowed:
            self.hint.emit("Start tracking in Reality first.")
            return None
        if self._take is not None:
            return self._take.path
        meta = {
            "room": self._room_id,
            "rung": 0,
            **(extra_meta or {}),
        }
        self._take = TakeWriter.start(meta)
        self.recording_changed.emit(True)
        self.hint.emit(f"Recording {self._take.path.name}")
        return self._take.path

    def stop_record(self) -> Path | None:
        take = self._take
        self._take = None
        if take is None:
            return None
        path = take.close()
        self.recording_changed.emit(False)
        self.hint.emit(f"Take saved ({take.frames} frames) {path}")
        return path

    def submit_frame(self, rgb: np.ndarray, t_capture: float, width: int, height: int) -> None:
        if not self.allowed or self._worker is None:
            return
        self._worker.submit(rgb, t_capture, width, height)

    def submit_video(self, frame: object, t_capture: float) -> None:
        if not self.allowed or self._worker is None:
            return
        self._worker.submit_video(frame, t_capture)

    def _on_hands(self, frame: HandsFrame) -> None:
        if not self.allowed:
            return
        state = self._gesture.step(frame)
        if self._last_t is not None:
            self._intervals.append(frame.t_capture - self._last_t)
        self._last_t = frame.t_capture
        control = self._gesture.hand
        if control is not None:
            wrist = control.xy(0)
            self._wrist_hist.append(
                (wrist[0] * frame.width, wrist[1] * frame.height)
            )
        self._last_frame = frame
        clicks = self._gesture.consume_clicks()
        self.last_state = state
        self.last_hand = control
        self.last_tracks = tuple(self._gesture.tracks)
        self.last_clicks = tuple(clicks)
        for click in clicks:
            hands_log.emit(
                "click",
                who=click.who,
                x=round(click.x, 4),
                y=round(click.y, 4),
                travel=round(click.travel, 4),
            )
            self.clicked.emit(click)
        fps = 0.0
        if self._intervals:
            mean = sum(self._intervals) / len(self._intervals)
            if mean > 1e-6:
                fps = 1.0 / mean
        self.last_fps = fps
        if self._take is not None:
            extra: dict[str, Any] = {"gesture": state}
            if self.scene_log is not None:
                extra["world"] = self.scene_log()
            if not self._take.write(frame, extra=extra):
                self.stop_record()
                self.hint.emit("Take capped (60 s or 2000 frames).")
                self.frame_ready.emit(frame)
                return
        self.frame_ready.emit(frame)
        tracks = [
            {
                "who": str(getattr(track, "who", "") or ""),
                "state": str(getattr(track, "state", "") or ""),
                "drag": bool(getattr(track, "dragging", False)),
            }
            for track in self.last_tracks
        ]
        hands_log.sample(
            "pose",
            n=len(frame.hands),
            state=state,
            fps=round(fps, 2),
            infer=f"{frame.infer_width}x{frame.infer_height}",
            preview=self._preview_wanted,
            tracks=tracks,
        )
        self.hint.emit(self._status_line(frame, state, fps))

    def _status_line(self, frame: HandsFrame, state: str, fps: float) -> str:
        rms = ""
        if len(self._wrist_hist) >= 10:
            xs = [p[0] for p in self._wrist_hist]
            ys = [p[1] for p in self._wrist_hist]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            acc = sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys, strict=True))
            val = (acc / len(xs)) ** 0.5
            rms = f" · still RMS {val:.1f}px"
        rec = " · rec" if self._take is not None else ""
        return (
            f"{len(frame.hands)} hand · {state} · {fps:.1f} fps · "
            f"{frame.width}x{frame.height} → {frame.infer_width}x{frame.infer_height}"
            f"{rms}{rec}"
        )
