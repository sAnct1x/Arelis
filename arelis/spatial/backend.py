"""Hand pose backends. MediaPipe Tasks is optional. Tests use a stub."""

from __future__ import annotations

import logging
import time
import urllib.request
from pathlib import Path
from typing import Protocol

import numpy as np

from arelis.paths import models_dir
from arelis.spatial import LANDMARK_NAMES
from arelis.spatial.types import Hand, HandsFrame, Landmark
from arelis.spatial.video import POSE_MAX_WIDTH

log = logging.getLogger(__name__)

INFER_MAX_WIDTH = POSE_MAX_WIDTH
HAND_MODEL_NAME = "hand_landmarker.task"
HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)


class PoseBackend(Protocol):
    name: str

    def infer(
        self, rgb: np.ndarray, t_capture: float, src_w: int, src_h: int
    ) -> HandsFrame: ...

    def close(self) -> None: ...


def video_clock_ms(t_capture: float, last_ms: int) -> int:
    """Monotonic ms for MediaPipe VIDEO mode.

    Adding 33 every call pretends the worker never drops a frame. It does —
    latest-frame-only — so the tracker is told the hand moved in 33 ms when
    the gap was 80. Landmarks then hunt, which is the jitter on a still hand.
    """
    guessed = round(float(t_capture) * 1000.0)
    if last_ms <= 0:
        return max(1, guessed)
    return max(last_ms + 1, guessed)


def downscale_rgb(rgb: np.ndarray, max_width: int = INFER_MAX_WIDTH) -> np.ndarray:
    """Shrink for the detector. Landmarks stay normalized, drawn on the full frame."""
    h, w = rgb.shape[:2]
    if w <= max_width:
        return rgb
    new_w = max_width
    new_h = max(1, round(h * (max_width / w)))
    # Integer box downsample — no cv2.
    y_idx = (np.linspace(0, h - 1, new_h)).astype(np.int32)
    x_idx = (np.linspace(0, w - 1, new_w)).astype(np.int32)
    return rgb[y_idx][:, x_idx]


def _landmarks_from_pairs(
    points: list[tuple[float, float, float]],
) -> tuple[Landmark, ...]:
    out: list[Landmark] = []
    for i, (x, y, z) in enumerate(points):
        name = LANDMARK_NAMES[i] if i < len(LANDMARK_NAMES) else f"pt{i}"
        out.append(Landmark(x=float(x), y=float(y), z=float(z), name=name))
    return tuple(out)


class StubBackend:
    """Deterministic empty result. Tests and missing-extra installs."""

    name = "stub"

    def infer(
        self, rgb: np.ndarray, t_capture: float, src_w: int, src_h: int
    ) -> HandsFrame:
        infer = downscale_rgb(rgb)
        return HandsFrame(
            t_capture=t_capture,
            t_infer=t_capture,
            width=src_w,
            height=src_h,
            infer_width=int(infer.shape[1]),
            infer_height=int(infer.shape[0]),
            hands=(),
            backend=self.name,
        )

    def close(self) -> None:
        return


def hand_model_path() -> Path:
    return models_dir() / "hands" / HAND_MODEL_NAME


def ensure_hand_model(allow_download: bool = True) -> Path | None:
    dest = hand_model_path()
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    if not allow_download:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    try:
        urllib.request.urlretrieve(HAND_MODEL_URL, tmp)
        tmp.replace(dest)
    except Exception as exc:
        log.warning("hand landmarker download failed: %s", exc)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return dest if dest.is_file() else None
    return dest if dest.is_file() else None


class TasksHandsBackend:
    """MediaPipe 1.x HandLandmarker, VIDEO mode."""

    name = "mediapipe.tasks.hand_landmarker"

    def __init__(self, model_path: Path) -> None:
        from mediapipe.tasks.python.core.base_options import BaseOptions
        from mediapipe.tasks.python.vision import (
            HandLandmarker,
            HandLandmarkerOptions,
            RunningMode,
        )

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.4,
            min_tracking_confidence=0.3,
        )
        self._landmarker = HandLandmarker.create_from_options(options)
        self._t_ms = 0

    def infer(
        self, rgb: np.ndarray, t_capture: float, src_w: int, src_h: int
    ) -> HandsFrame:
        from mediapipe import Image, ImageFormat

        infer = np.ascontiguousarray(downscale_rgb(rgb))
        self._t_ms = video_clock_ms(t_capture, self._t_ms)
        t0 = time.perf_counter()
        image = Image(image_format=ImageFormat.SRGB, data=infer)
        result = self._landmarker.detect_for_video(image, self._t_ms)
        t1 = time.perf_counter()
        hands: list[Hand] = []
        landmarks = result.hand_landmarks or []
        handed = result.handedness or []
        for i, lm_list in enumerate(landmarks):
            label = "Unknown"
            score = 0.0
            if i < len(handed) and handed[i]:
                label = str(getattr(handed[i][0], "category_name", "Unknown"))
                score = float(getattr(handed[i][0], "score", 0.0))
            pts = [
                (float(p.x), float(p.y), float(getattr(p, "z", 0.0))) for p in lm_list
            ]
            hands.append(
                Hand(label=label, landmarks=_landmarks_from_pairs(pts), score=score)
            )
        return HandsFrame(
            t_capture=t_capture,
            t_infer=t1 - t0,
            width=src_w,
            height=src_h,
            infer_width=int(infer.shape[1]),
            infer_height=int(infer.shape[0]),
            hands=tuple(hands),
            backend=self.name,
        )

    def close(self) -> None:
        close = getattr(self._landmarker, "close", None)
        if callable(close):
            close()


def load_backend() -> PoseBackend:
    try:
        import mediapipe  # noqa: F401
    except ImportError:
        log.info("mediapipe not installed; spatial extra is off")
        return StubBackend()
    model = ensure_hand_model()
    if model is None:
        log.warning("hand landmarker model missing")
        return StubBackend()
    try:
        return TasksHandsBackend(model)
    except Exception as exc:
        log.warning("MediaPipe HandLandmarker failed: %s", exc)
        return StubBackend()
