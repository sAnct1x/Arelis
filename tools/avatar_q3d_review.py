"""Render the Quick 3D aether port for Iris's review kit (team/avatar-proto/qq3d-review).

The kit fixes the poses: index-mixer.html (locked aether.js) with seed 4242 / aseed 6, her
camera, setState + mixerPlay, then N steps of __step(1/30) with setLevel before each step.
That frame includes anim.js's procedural motion on top of the clip, so a bare clip cannot
match it. This tool runs the kit's page the same way and copies, per pose, the local
transform of every bone, every aether uniform and the camera onto the Quick 3D scene, then
renders <pose>.png at 720x960. Morph targets (blink, visemes) are not ported yet.

  web:  python tools/avatar_q3d_review.py web  --out DIR   (playwright, kit server on :8765)
  qq3d: python tools/avatar_q3d_review.py qq3d --out DIR   (PySide6, under xvfb-run)
"""
# ruff: noqa: E501  (embedded JS reads better unwrapped)

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import avatar_lookmatch as lm
from avatar_q3d_export import UNIFORMS_JS, WORLD_JS

KIT = Path("/workspace/team/avatar-proto/qq3d-review")
URL = "http://127.0.0.1:8765/threejs-prep/index-mixer.html?view=full&manual=1&seed=4242&aseed=6"
W, H, FPS = 720, 960, 30
FRONT = ([0, 0.9, 3.95], [0, 0.88, 0])
HUB = ([0.35, 0.9, 3.95], [0.35, 0.88, 0])  # kit placeholder: camera slid +0.35 m on X
POSES = {  # state, clip, level, frames, camera (same table as the kit's render_ref.py)
    "idle": ("idle", "Idle", 0.0, 60, FRONT),
    "talking": ("speaking", "Talking", 0.7, 60, FRONT),
    "blink": ("idle", "Idle", 0.0, 89, FRONT),
    "happy": ("idle", "v2_HappyIdle", 0.0, 60, FRONT),
    "listening": ("listening", "Listening", 0.0, 60, FRONT),
    "hub": ("idle", "Idle", 0.0, 60, HUB),
}
BONES_JS = """() => { const b = {}; window.__root.traverse((o) => { if (o.isBone) b[o.name] = [o.position.toArray(), o.quaternion.toArray(), o.scale.toArray()]; });
  const c = window.__cam; return { bones: b, fov: c.fov, near: c.near, far: c.far }; }"""
SET_BONES_QML = """
    function setBones(b) {
        var d = ellah.data
        for (var i = 0; i < d.length; i++) if (d[i].objectName && d[i].animations !== undefined) d[i].enabled = false
        for (var n in b) { var o = find(ellah, n); if (!o) continue; var t = b[n]
            o.position = Qt.vector3d(t[0][0], t[0][1], t[0][2]); o.rotation = Qt.quaternion(t[1][3], t[1][0], t[1][1], t[1][2])
            o.scale = Qt.vector3d(t[2][0], t[2][1], t[2][2]) }
        return true
    }
    function find(o, n) { if (o.objectName === n) return o; var k = o.children || []
        for (var i = 0; i < k.length; i++) { var r = find(k[i], n); if (r) return r } return null }
"""


def run_web(out: Path) -> None:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    state = {}
    args = [
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--ignore-gpu-blocklist",
    ]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=args)
        for name, (st, clip, level, frames, (pos, look)) in POSES.items():
            pg = b.new_page(viewport={"width": W, "height": H})
            pg.goto(URL, wait_until="commit", timeout=120000)
            pg.wait_for_function(
                "window.__ready && window.avatar && window.avatar.mixerReady", timeout=180000
            )
            ps, lk = ",".join(map(str, pos)), ",".join(map(str, look))
            pg.evaluate(
                f"(()=>{{const c=window.__cam;c.position.set({ps});c.lookAt({lk});c.aspect={W}/{H};c.updateProjectionMatrix();}})()"
            )
            pg.evaluate(f"window.avatar.setState('{st}')")
            pg.evaluate(f"window.avatar.mixerPlay('{clip}',0)")
            for _ in range(frames):
                pg.evaluate(f"window.avatar.setLevel({level}); window.__step({1 / FPS})")
            pg.screenshot(path=str(out / f"v14k-{name}.png"))
            s = pg.evaluate(BONES_JS)
            s.update(
                uniforms=pg.evaluate(UNIFORMS_JS),
                worlds=pg.evaluate(WORLD_JS),
                pos=pos,
                look=look,
                level=level,
            )
            state[name] = s
            print("web", name, len(s["uniforms"]), "layers", len(s["bones"]), "bones", flush=True)
            pg.close()
        b.close()
    (out / "review_state.json").write_text(json.dumps(state))


def run_qq3d(out: Path, qml_dir: Path) -> None:
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication, QSurfaceFormat, QVector3D
    from PySide6.QtQuick import QQuickView
    from PySide6.QtQuick3D import QQuick3D

    sys.path.insert(0, str(lm.REPO))
    import arelis.ui.persona_q3d.geometry  # noqa: F401  (registers Arelis.PersonaQ3D)

    state = json.loads((out / "review_state.json").read_text())
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    QSurfaceFormat.setDefaultFormat(QQuick3D.idealSurfaceFormat())
    for name, s in state.items():
        src = out / "_review.qml"
        glow = {**lm.GLOW, **json.loads(os.environ.get("AETHER_GLOW", "{}"))}
        qml = lm.QML % {
            "imports": "import QtQuick3D.Helpers\nimport Arelis.PersonaQ3D",
            "scene": lm.PORT_SCENE % {"fov": s["fov"], "near": s["near"], "far": s["far"], **glow},
            "conv": qml_dir.resolve().as_uri(),
            "w": W,
            "h": H,
            "vx": 0,
            "vw": W,
        }
        src.write_text(qml[: qml.rindex("}")] + SET_BONES_QML + "}\n")
        v = QQuickView()
        v.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        v.resize(W, H)
        v.setSource(QUrl.fromLocalFile(str(src)))
        if v.status() != QQuickView.Status.Ready:
            raise SystemExit("qq3d: " + "; ".join(e.toString() for e in v.errors()))
        v.show()
        r = v.rootObject()
        r.pose("none", 0, QVector3D(*s["pos"]), QVector3D(*s["look"]))
        r.setBones(s["bones"])
        r.setProperty("speakingLevel", s["level"])
        lm._apply_uniforms(r, s["uniforms"], s["worlds"])
        loop = QEventLoop()
        QTimer.singleShot(2500, loop.quit)
        loop.exec()
        v.grabWindow().save(str(out / f"{name}.png"))
        print("qq3d", name, flush=True)
        v.close()
        v.deleteLater()
    del app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("web", "qq3d"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--qml-dir", type=Path, default=Path("/workspace/team/avatar-qq3d/converted"))
    a = ap.parse_args(argv)
    run_web(a.out) if a.cmd == "web" else run_qq3d(a.out, a.qml_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
