"""Webcam still capture for look-on-ask vision.

UI owns the live camera session. When the dock is running, config["_camera_capture"]
is set to CameraPanel.snapshot_blocking. Otherwise reuse a fresh camera_*.jpg
(< ~30s) or fail with operator guidance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arelis.config import PROJECT_ROOT
from arelis.core.image_refs import CAMERA_FRESH_S, latest_camera_image_file
from arelis.tools.base import ToolResult


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
        raw = Path(path)
        try:
            return str(raw.resolve().relative_to(PROJECT_ROOT.resolve())).replace(
                "\\", "/"
            )
        except ValueError:
            return str(raw).replace("\\", "/")

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

        return ToolResult(
            ok=False,
            output=(
                "No live camera session and no fresh camera_*.jpg under "
                "outputs/images/. Open View → camera (or Ctrl+5), start the "
                "preview, then use Ask Arelis or snapshot — or ask again while "
                "the camera dock is open."
            ),
        )
