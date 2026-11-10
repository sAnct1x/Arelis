"""The Overseer's compiled pipelines are saved when it closes and seed the next start."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Runs in a child on a real platform: offscreen releases the scene's QRhi when it
# hides, while the threaded render loop on a desktop keeps it, which is what is saved.
_CHILD = r"""
import os, sys, time
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from arelis import sentinel_control
from arelis.ui import sentinel_host
assets = Path(sys.argv[1])
# A Quick 3D material, like the real scene: its shaders are generated and compiled
# at run time. Qt Quick's own 2D shaders ship as precompiled DXBC on Windows, so a
# 2D-only stub never compiles anything on D3D11 and its QRhi has nothing to save.
(assets / "OverseerView.qml").write_text(
    "import QtQuick\nimport QtQuick3D\n"
    "View3D { width: 64; height: 64\n"
    " PerspectiveCamera { z: 300 }\n DirectionalLight {}\n"
    " Model { source: '#Cube'; materials: PrincipledMaterial { baseColor: 'red' } } }\n"
)
sentinel_control.overseer_url = lambda: "http://127.0.0.1:9/#tok"
sentinel_control.bridge_target = lambda: None
win = sentinel_host.SentinelWindow(None)
win._asset_dir = lambda: assets
win.show()
end = time.monotonic() + 1.0
while time.monotonic() < end:
    app.processEvents()
    time.sleep(0.01)
rhi = win._scene.rhi()
if rhi is not None and rhi.backendName() == "Metal":
    print("NO_DATA"); sys.stdout.flush(); os._exit(0)
win.hide()
app.processEvents()
path = sentinel_host.overseer_pipeline_cache_path()
saved = path.is_file() and path.stat().st_size > 0
if not saved:
    rhi = win._scene.rhi()
    data = rhi.pipelineCacheData() if rhi is not None else b""
    print("diag visible", win._scene.isVisible(), "rhi", None if rhi is None else rhi.backendName(), "data", len(data))
nxt = sentinel_host.SentinelWindow(None)
nxt._asset_dir = lambda: assets
seeded = nxt._ensure_scene().graphicsConfiguration().pipelineCacheLoadFile() == str(path)
print("saved", saved, "seeded", seeded)
sys.stdout.flush()
os._exit(0)
"""


def test_close_saves_the_pipeline_cache_and_the_next_scene_loads_it(tmp_path) -> None:
    # Atria: the Overseer's QRhi collected nothing (0 vs her 65 shaders), so every
    # start compiled every pipeline again in a 1.1 s first frame.
    platform = {"win32": "windows", "darwin": "cocoa"}.get(sys.platform, "xcb")
    if platform == "xcb" and not os.environ.get("DISPLAY"):
        pytest.skip("needs a display (xvfb-run)")
    env = dict(os.environ, QT_QPA_PLATFORM=platform, ARELIS_DATA_DIR=str(tmp_path / "data"))
    env.pop("QT_QUICK_BACKEND", None)
    out = subprocess.run(
        [sys.executable, "-c", _CHILD, str(tmp_path)],
        cwd=_ROOT, env=env, capture_output=True, text=True, timeout=90,
    )
    if "NO_DATA" in out.stdout:
        pytest.skip("Metal gives no pipeline cache data")
    assert "saved True seeded True" in out.stdout, out.stdout + out.stderr[-2000:]
