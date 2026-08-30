"""Owned-camera stills and local face boxes. Not a model name.

Any USB index or RTSP URL the operator pasted. Boxes stay on this
machine, in local ENU, on the people layer with pii=inferred. They are
not a search index. Stream URLs never land in entity meta, dumps, or
cites. Cameras we do not own are out.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import yaml

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import enu_to_ecef
from arelis.paths import state_dir

SECRETS_PATH = state_dir() / "secrets.yaml"
_CITE = (
    "Owned camera still. Local face box in ENU. Not a name. "
    "Not a global face index. Stream URL is not stored."
)
_CAP = 32


def load_owned_faces(path: Path | None = None) -> list[Entity]:
    """Best-effort. Empty if no pose, no frame, or tests muted the camera."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    rows = _owned_rows(path)
    out: list[Entity] = []
    for row in rows:
        boxes = _boxes_for_row(row)
        if not boxes:
            continue
        out.extend(
            entities_from_boxes(
                str(row.get("id") or "cam"),
                float(row["_lat"]),
                float(row["_lon"]),
                float(row.get("_heading") or 0.0),
                float(row.get("_fov") or 70.0),
                boxes,
            )
        )
        if len(out) >= _CAP:
            break
    return out[:_CAP]


def entities_from_boxes(
    cam_id: str,
    lat: float,
    lon: float,
    heading_deg: float,
    fov_deg: float,
    boxes: list[tuple[float, float, float, float]],
    *,
    range_m: float = 12.0,
) -> list[Entity]:
    """Normalized image boxes (cx, cy, w, h) in 0–1 → people pins in ENU.

    x right, y down, like a camera frame. Lower in the frame is closer.
    """
    out: list[Entity] = []
    fov = max(10.0, min(120.0, fov_deg))
    for i, box in enumerate(boxes):
        if len(box) < 4:
            continue
        cx, cy, _w, _h = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
            continue
        az = (cx - 0.5) * fov
        dist = range_m * (0.35 + 0.65 * max(0.0, min(1.0, cy)))
        heading = math.radians(heading_deg + az)
        east = dist * math.sin(heading)
        north = dist * math.cos(heading)
        x, y, z = enu_to_ecef(lat, lon, east, north, 1.6)
        eid = f"owned:{cam_id.casefold()[:32]}:face:{i}"
        out.append(
            Entity(
                id=eid,
                cls="person",
                layer="people",
                label="local box",
                x=x,
                y=y,
                z=z,
                source="owned camera",
                freshness="live",
                confidence=0.45,
                cite=_CITE,
                meta={"lat": lat, "lon": lon, "cam": cam_id.casefold()[:32]},
                pii="inferred",
                coverage=Coverage(
                    "owned",
                    "Local ENU box. Not identified. Does not leave this machine.",
                ),
            )
        )
        if len(out) >= _CAP:
            break
    return out


def _owned_rows(path: Path | None) -> list[dict[str, Any]]:
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(raw, dict):
        return []
    block = raw.get("earth")
    if not isinstance(block, dict):
        return []
    rows: list[dict[str, Any]] = []
    local = block.get("local_camera")
    if isinstance(local, dict):
        rows.append(local if local.get("id") else {**local, "id": "local"})
    cams = block.get("cameras")
    if isinstance(cams, list):
        rows.extend(row for row in cams if isinstance(row, dict))
    out: list[dict[str, Any]] = []
    for row in rows:
        lat = _num(row.get("lat"), row.get("latitude"))
        lon = _num(row.get("lon"), row.get("longitude"))
        if lat is None or lon is None:
            continue
        if abs(lat) > 90.0 or abs(lon) > 180.0:
            continue
        rtsp = str(row.get("rtsp") or row.get("url") or "").strip()
        device = row.get("device")
        if device is None:
            device = row.get("index") or row.get("device_index")
        if not rtsp and device is None:
            continue
        packed = dict(row)
        packed["_lat"] = lat
        packed["_lon"] = lon
        packed["_heading"] = _num(row.get("heading_deg")) or 0.0
        packed["_fov"] = _num(row.get("fov_deg")) or 70.0
        out.append(packed)
    return out


def _boxes_for_row(row: dict[str, Any]) -> list[tuple[float, float, float, float]]:
    frame = _grab_frame(row)
    if frame is None:
        return []
    return detect_faces(frame)


def _grab_frame(row: dict[str, Any]) -> Any:
    try:
        import numpy as np
    except ImportError:
        return None
    source: Any = row.get("rtsp") or row.get("url") or row.get("device")
    if source is None or source == "":
        return None
    try:
        import cv2
    except ImportError:
        return None
    cap = None
    try:
        cap = cv2.VideoCapture(source)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2500)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2500)
        ok, bgr = cap.read()
        if not ok or bgr is None:
            return None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return np.ascontiguousarray(rgb)
    except Exception:
        return None
    finally:
        if cap is not None:
            cap.release()


def detect_faces(rgb: Any) -> list[tuple[float, float, float, float]]:
    """Return normalized (cx, cy, w, h). Empty if MediaPipe is missing."""
    try:
        import numpy as np
        from mediapipe import Image, ImageFormat
        from mediapipe.tasks.python.core.base_options import BaseOptions
        from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions
    except ImportError:
        return []
    model = _face_model_path()
    if model is None:
        return []
    try:
        options = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(model)),
            min_detection_confidence=0.5,
        )
        detector = FaceDetector.create_from_options(options)
        image = Image(image_format=ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = detector.detect(image)
    except Exception:
        return []
    h, w = int(rgb.shape[0]), int(rgb.shape[1])
    if w < 1 or h < 1:
        return []
    out: list[tuple[float, float, float, float]] = []
    for det in result.detections or []:
        box = getattr(det, "bounding_box", None)
        if box is None:
            continue
        origin_x = float(getattr(box, "origin_x", 0.0))
        origin_y = float(getattr(box, "origin_y", 0.0))
        width = float(getattr(box, "width", 0.0))
        height = float(getattr(box, "height", 0.0))
        cx = (origin_x + width * 0.5) / w
        cy = (origin_y + height * 0.5) / h
        out.append((cx, cy, width / w, height / h))
        if len(out) >= _CAP:
            break
    return out


def _face_model_path() -> Path | None:
    from arelis.paths import models_dir

    dest = models_dir() / "faces" / "blaze_face_short_range.tflite"
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    return None


def _num(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
