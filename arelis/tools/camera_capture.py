"""Webcam still capture for look-on-ask vision.

UI owns the live camera session. When the dock is running, config["_camera_capture"]
is set to CameraPanel.snapshot_blocking. Otherwise reuse a fresh camera_*.jpg
(< ~30s) or fail with operator guidance.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.core.image_refs import CAMERA_FRESH_S, latest_camera_image_file
from arelis.paths import display_path, outputs_dir
from arelis.tools.base import ToolResult


def _grab_webcam_still() -> Path | None:
    """One frame from the default webcam when the dock is not open."""
    try:
        import cv2
    except ImportError:
        return None
    cap = None
    try:
        cap = cv2.VideoCapture(0)
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4000)
        except Exception:
            pass
        if not cap.isOpened():
            return None
        ok, bgr = cap.read()
        if not ok or bgr is None:
            return None
        out_dir = outputs_dir() / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = out_dir / f"camera_{stamp}.jpg"
        if not cv2.imwrite(str(dest), bgr):
            return None
        return dest
    except Exception:
        return None
    finally:
        if cap is not None:
            cap.release()


class CameraTool:
    name = "camera"
    description = (
        "Capture or reuse a webcam still under outputs/images/camera_*.jpg. "
        "action=snapshot: use the live camera dock when open, else a fresh "
        "frame (<30s), else tell the operator to open View → camera / Ask Arelis. "
        "Then call vision on the returned path. Not ambient watching."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["snapshot"],
                "description": "Only snapshot is supported.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def _rel_path(self, path: str | Path) -> str:
        return display_path(path)

    async def run(self, action: str = "snapshot", **_kwargs: Any) -> ToolResult:
        act = (action or "snapshot").strip().lower()
        if act != "snapshot":
            return ToolResult(
                ok=False,
                output=f"Unknown camera action {action!r}; use action=snapshot.",
            )

        capturer = self.config.get("_camera_capture")
        if callable(capturer):
            try:
                captured = capturer()
            except Exception as exc:
                return ToolResult(
                    ok=False,
                    output=f"Camera capture failed: {exc}",
                )
            if captured:
                rel = self._rel_path(captured)
                return ToolResult(
                    ok=True,
                    output=(
                        f"Saved camera frame to {rel}. Call vision with path={rel}."
                    ),
                    data={"path": rel},
                )

        fresh = latest_camera_image_file(max_age_s=CAMERA_FRESH_S)
        if fresh:
            return ToolResult(
                ok=True,
                output=(
                    f"Reusing fresh camera frame {fresh} "
                    f"(under {int(CAMERA_FRESH_S)}s). Call vision with path={fresh}."
                ),
                data={"path": fresh},
            )

        grabbed = await asyncio.to_thread(_grab_webcam_still)
        if grabbed:
            rel = self._rel_path(grabbed)
            return ToolResult(
                ok=True,
                output=(
                    f"Saved camera frame to {rel} (direct webcam, dock was "
                    f"closed). Call vision with path={rel}."
                ),
                data={"path": rel},
            )

        return ToolResult(
            ok=False,
            output=(
                "No live camera session and no fresh camera_*.jpg under "
                "outputs/images/. Open View → camera (or Ctrl+5), start the "
                "preview, then use Ask Arelis or snapshot — or ask again while "
                "the camera dock is open."
            ),
        )
