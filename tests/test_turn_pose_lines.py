"""Each pose she takes in a turn lands in the log as a ``clip play`` line, and the bridge keeps done and listening."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from tests.pose_bridge_diagnostics import NODE_MARKERS, run_bridge
from tests.test_scene_loads_visible import _FakeScene

WEB = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "persona_face" / "web"


def test_a_turn_logs_thinking_speaking_done_and_back_to_idle(monkeypatch, caplog) -> None:
    QApplication.instance() or QApplication([])
    from arelis.ui.persona_face import PersonaPanel, web_avatar

    monkeypatch.setattr(web_avatar, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _FakeScene)
    caplog.set_level(logging.INFO, logger="arelis.avatar")
    panel = PersonaPanel()
    for state in ("thinking", "thinking", "speaking", "done", "rest"):
        panel.set_state(state)
    plays = [r.getMessage() for r in caplog.records if "clip play" in r.getMessage()]
    assert plays == [
        "[avatar] clip play name=thinking",
        "[avatar] clip play name=speaking",
        "[avatar] clip play name=done",
        "[avatar] clip play name=idle",
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_bridge_passes_done_and_listening_to_her_poses(tmp_path) -> None:
    script = tmp_path / "bridge.js"
    script.write_text(
        NODE_MARKERS
        + "const sent = []; globalThis.window = { aether: { setState: (m) => sent.push(m) } };\n"
        "globalThis.addEventListener = () => {};\n"
        + (WEB / "avatar-api.js").read_text(encoding="utf-8")
        + "\n__poseDiagnostic('bridge-defined');\n"
        + "for (const s of ['thinking', 'speaking', 'done', 'listening', 'rest']) window.avatar.setState(s);\n"
        "__poseDiagnostic('transitions-complete');\n"
        "console.log(JSON.stringify(sent));\n"
        "__poseDiagnostic('stdout-call-returned', true);\n",
        encoding="utf-8",
    )
    out = run_bridge(script)
    assert json.loads(out.stdout) == ["thinking", "talking", "done", "listening", "idle"]
