"""Box check for the Quick 3D body mixer (arelis/ui/persona_q3d/Mixer.qml).

Frame grabs across a state change.

  xvfb-run -a python tools/avatar_mixer_check.py --qml-dir DIR_WITH_converted --out DIR

Steps the mixer by hand at a fixed dt (no wall clock), so runs repeat. Writes frame PNGs around
the switch, a CSV of per-frame clip, fade weight, bone steps and consecutive-frame pixel diffs,
and summary.json.
The converted model is private: point --qml-dir at it, never copy it into the repo.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "arelis/ui/persona_q3d"

QML = """
import QtQuick
import QtQuick3D
import "%(conv)s"
import "%(mix)s"
Item {
    width: %(w)d; height: %(h)d
    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            clearColor: "#14101c"; backgroundMode: SceneEnvironment.Color }
        PerspectiveCamera {
            position: Qt.vector3d(0, 95, 330); clipNear: 1; clipFar: 5000; fieldOfView: 35 }
        DirectionalLight { eulerRotation.x: -30; eulerRotation.y: 20; brightness: 1.2 }
        DirectionalLight {
            eulerRotation.x: -10; eulerRotation.y: 200; brightness: 0.5; color: "#b9a6ff" }
        Ellah_anim { id: ellah; scale: Qt.vector3d(100, 100, 100) }
    }
    Mixer { id: mixer; objectName: "mixer"; model: ellah; running: false }
    function start() { mixer.init() }
    function step(dt) { mixer.tick(dt); return [mixer.clip, mixer.weight, mixer.mode] }
    function changeState(s) { mixer.setState(s) }
    function bone(name) {
        var r = null
        function walk(n) { if (r) return; if (n.objectName === name) { r = n; return }
            for (var i = 0; i < n.children.length; i++) walk(n.children[i]) }
        walk(ellah)
        var q = r.rotation
        return [q.scalar, q.x, q.y, q.z]
    }
}
"""

BONES = [
    "CC_Base_Spine02",
    "CC_Base_L_Upperarm",
    "CC_Base_R_Forearm",
    "CC_Base_L_Thumb2",
    "CC_Base_R_Thumb3",
]


def ang(a, b) -> float:
    d = abs(sum(x * y for x, y in zip(a, b, strict=True)))
    return math.degrees(2 * math.acos(min(1.0, d)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qml-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="360x480")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--pre", type=float, default=3.0, help="seconds of idle before the switch")
    ap.add_argument("--post", type=float, default=1.5, help="seconds after the switch")
    ap.add_argument("--to", default="listening")
    ap.add_argument("--from-state", default="idle")
    a = ap.parse_args()
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    import numpy as np
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication, QSurfaceFormat
    from PySide6.QtQuick import QQuickView
    from PySide6.QtQuick3D import QQuick3D

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    w, h = (int(x) for x in a.size.split("x"))
    app = QGuiApplication(sys.argv[:1])
    QSurfaceFormat.setDefaultFormat(QQuick3D.idealSurfaceFormat())
    src = out / "_mixer.qml"
    src.write_text(
        QML
        % {
            "conv": (Path(a.qml_dir) / "converted").resolve().as_uri(),
            "mix": HERE.resolve().as_uri(),
            "w": w,
            "h": h,
        }
    )
    v = QQuickView()
    v.resize(w, h)
    v.setSource(QUrl.fromLocalFile(str(src)))
    if v.status() != QQuickView.Status.Ready:
        raise SystemExit("; ".join(e.toString() for e in v.errors()))
    v.show()
    app.processEvents()
    r = v.rootObject()
    r.start()
    r.changeState(a.from_state)
    dt = 1.0 / a.fps
    rows, prev_img, prev_q = [], None, None
    n_pre, n_post = round(a.pre * a.fps), round(a.post * a.fps)
    for i in range(n_pre + n_post):
        if i == n_pre:
            r.changeState(a.to)
        clip, wt, mode = r.step(dt).toVariant()
        app.processEvents()
        q = {b: r.bone(b).toVariant() for b in BONES}
        grab = i >= n_pre - 6
        diff = None
        if grab:
            img = v.grabWindow()
            arr = np.asarray(img.convertToFormat(img.Format.Format_RGB888).constBits()).reshape(
                h, -1
            )[:, : w * 3]
            arr = arr.astype(int)
            if prev_img is not None:
                diff = float(np.abs(arr - prev_img).mean())
            prev_img = arr
            img.save(str(out / f"f{i:04d}.png"))
        step = {b: (ang(q[b], prev_q[b]) if prev_q else 0.0) for b in BONES}
        prev_q = q
        rows.append(
            {
                "i": i,
                "t": round(i * dt, 4),
                "mode": mode,
                "clip": clip,
                "w": round(wt, 4),
                "pixdiff": diff,
                **{f"dq_{b}": round(step[b], 4) for b in BONES},
            }
        )
    with open(out / "frames.csv", "w") as f:
        keys = list(rows[0])
        f.write(",".join(keys) + "\n")
        for row in rows:
            f.write(",".join("" if row[k] is None else str(row[k]) for k in keys) + "\n")
    win = [x for x in rows if x["i"] >= n_pre - 5]
    fade = [x for x in rows if x["w"] < 1]
    steady = [x for x in rows[n_pre - 40 : n_pre] if x["w"] == 1]
    summ = {
        "switch_frame": n_pre,
        "from_clip": rows[n_pre - 1]["clip"],
        "to_clip": rows[-1]["clip"],
        "fade_frames": len(fade),
        "weights": [x["w"] for x in fade],
        "max_pixdiff_window": max(x["pixdiff"] or 0 for x in win),
        "max_pixdiff_fade": max((x["pixdiff"] or 0 for x in fade), default=0),
        "max_bone_step_deg_fade": max((max(x[f"dq_{b}"] for b in BONES) for x in fade), default=0),
        "max_bone_step_deg_steady": max(
            (max(x[f"dq_{b}"] for b in BONES) for x in steady), default=0
        ),
    }
    (out / "summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ))
    src.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
