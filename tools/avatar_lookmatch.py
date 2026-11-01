# ruff: noqa: E501  (embedded JS and QML snippets read better unwrapped)
"""Look-match harness: v14k (WebEngine/three.js page) against the Qt Quick 3D candidate.

Box only. Renders both at the same 6 poses, camera and size with software GL, then writes
side-by-side sheets, heat maps and per-region diff numbers (face, hair, body, rim, halo,
background). The model files are private and are never copied into the repo: pass their paths.

  python tools/avatar_lookmatch.py web   --out DIR [--glb ellah.glb --clips ellah-anim.glb]
  xvfb-run -a python tools/avatar_lookmatch.py qq3d --out DIR --qml-dir DIR_WITH_converted
  python tools/avatar_lookmatch.py compare --out DIR
  python tools/avatar_lookmatch.py all --out DIR --qml-dir ... (web and qq3d in subprocesses)

web needs playwright and google-chrome (SwiftShader); qq3d needs PySide6 with QtQuick3D
(llvmpipe via QSG_RHI_BACKEND=opengl). Time is fixed (playwright clock, 100 ms steps) and
Math.random is seeded, so two runs of the same tree give the same PNGs.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB_DIR = REPO / "arelis" / "ui" / "persona_face" / "web"
PRIVATE = Path("/workspace/team/avatar-proto/threejs-prep")
SIZE = (720, 960)
STEPS = (
    30  # 30 frames x 100 ms = 3 s of clip time after the pose is set (page clock, not wall time)
)
HUB_PAN = 0.22  # Filament hub offset: camera pans so she sits this fraction of the width off centre

# name: (state, level, clip, blink hold, hub pan)
POSES: dict[str, tuple[str, float, str, float | None, float]] = {
    "idle": ("idle", 0.0, "Idle", None, 0.0),
    "talking": ("speaking", 0.9, "Talking", None, 0.0),
    "blink": ("idle", 0.0, "Idle", 1.0, 0.0),
    "happy": ("idle", 0.0, "v2_HappyIdle", None, 0.0),
    "listening": ("listening", 0.0, "Listening", None, 0.0),
    "hub": ("idle", 0.0, "Idle", None, HUB_PAN),
}
REGIONS = ("face", "hair", "body", "rim", "halo", "background")
# Plan thresholds: face and body mean dRGB < 6 and < 2% of pixels over 30; bloom/particles < 10 mean.
LIMITS = {
    "face": (6, 2.0),
    "body": (6, 2.0),
    "hair": (6, 2.0),
    "rim": (10, None),
    "halo": (10, None),
    "background": (10, None),
}

SEED_JS = (
    "(() => { let s = 12345; Math.random = () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s);"
    " t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })();"
)
POSE_JS = """([state, level, clip, blink]) => { const A = window.avatar; A.setState(state); A.setLevel(level);
  if (blink !== null) window.aether.holdBlink(blink); A.mixerPlay(clip, 0); return true; }"""
# Hub offset as an off-axis view (three.js setViewOffset): the image slides sideways, the projection
# stays the same, and fitView cannot undo it. The QQ3D side renders a wider View3D and crops.
PAN_JS = """(pan) => { const c = window.__cam; c.setViewOffset(innerWidth, innerHeight, -pan * innerWidth, 0, innerWidth, innerHeight); return true; }"""
CAM_JS = """() => { const c = window.__cam, M = window.avatar.mixer; const d = c.getWorldDirection(new window.__V3());
  const look = c.position.clone().add(d.multiplyScalar(c.position.distanceTo(window.__look)));
  return { pos: c.position.toArray(), look: look.toArray(), fov: c.fov, near: c.near, far: c.far,
    clip: M.curName, clipTime: M.cur ? M.cur.time : null }; }"""
# Mask pass: original meshes in flat colours (body red, hair green, face parts blue), everything else hidden.
MASK_JS = """() => { const root = window.__root, scene = root.parent, saved = [];
  const V = window.__V3, cls = (o) => /Hair|Female_Angled/.test(o.parent.name) ? 0x00ff00 : /Eye|Teeth|Tongue/.test(o.parent.name + o.name) ? 0x0000ff : 0xff0000;
  scene.children.forEach((o) => { saved.push([o, o.visible]); if (o !== root) o.visible = false; });
  root.traverse((o) => { if (!(o.isMesh || o.isPoints)) return; saved.push([o, o.visible]);
    if (!o.name || !o.isSkinnedMesh || o.material.type === 'ShaderMaterial') { o.visible = false; return; }
    if (!o.visible) return; const m = o.material; saved.push([o, m, 'm']);
    o.material = new m.constructor({ color: cls(o), transparent: false, depthWrite: true, depthTest: true }); });
  const bg = scene.background; scene.background = null; const r = window.__renderer; const cc = r.getClearAlpha();
  r.setClearColor(0x000000, 1); r.setRenderTarget(null); r.render(scene, window.__cam);
  const url = r.domElement.toDataURL('image/png');
  for (const s of saved.reverse()) { if (s[2] === 'm') s[0].material = s[1]; else s[0].visible = s[1]; }
  scene.background = bg; r.setClearAlpha(cc);
  const pr = (n) => { const b = root.getObjectByName(n), v = b.getWorldPosition(new V()).project(window.__cam);
    return [(v.x + 1) / 2 * innerWidth, (1 - v.y) / 2 * innerHeight]; };
  return { url, neck: pr('CC_Base_NeckTwist01'), head: pr('CC_Base_Head') }; }"""


def _serve(
    glb: Path, clips: Path
) -> tuple[str, http.server.ThreadingHTTPServer, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory(prefix="lookmatch-site-")
    site = Path(tmp.name)
    for f in WEB_DIR.iterdir():
        (site / f.name).symlink_to(f)
    (site / "models").mkdir()
    (site / "models" / "ellah.glb").symlink_to(glb)
    (site / "ellah-anim.glb").symlink_to(clips)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=str(site))
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}/index.html", srv, tmp


def run_web(out: Path, glb: Path, clips: Path) -> None:
    import base64

    from playwright.sync_api import sync_playwright

    url, srv, tmp = _serve(glb, clips)
    args = [
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--ignore-gpu-blocklist",
    ]
    out.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=args)
        for name, (state, level, clip, blink, pan) in POSES.items():
            pg = b.new_page(viewport={"width": SIZE[0], "height": SIZE[1]})
            pg.add_init_script(SEED_JS)
            pg.clock.install(time=0)
            pg.clock.pause_at(1000)  # install alone lets page time run with the wall clock
            pg.goto(url)
            t0 = time.time()
            ready = "!!(window.__ready && window.avatar && window.avatar.mixerReady) || !!window.__error"
            while not pg.evaluate(ready):
                time.sleep(0.2)  # page time stays at 0 while assets load, so every run starts alike
                if time.time() - t0 > 240:
                    raise SystemExit(f"web {name}: page not ready")
            if pg.evaluate("window.__error || null"):
                raise SystemExit(f"web {name}: {pg.evaluate('window.__error')}")
            for _ in range(100):  # let the materialize finish so every pose starts fully present
                if pg.evaluate("(window.avatar.appear ?? 1) >= 1"):
                    break
                pg.clock.fast_forward(100)
            pg.evaluate(_GRAB_INTERNALS)
            pg.evaluate(POSE_JS, [state, level, clip, blink])
            for _ in range(STEPS):
                pg.clock.fast_forward(100)
            if pan:
                pg.evaluate(PAN_JS, pan)
                pg.clock.fast_forward(100)
                pg.clock.fast_forward(100)
            cam = pg.evaluate(CAM_JS)
            pg.screenshot(path=str(out / f"v14k-{name}.png"))
            m = pg.evaluate(MASK_JS)
            (out / f"mask-{name}.png").write_bytes(base64.b64decode(m["url"].split(",", 1)[1]))
            meta[name] = {
                "camera": cam,
                "neck": m["neck"],
                "head": m["head"],
                "state": state,
                "level": level,
                "blink": blink,
                "pan": pan,
            }
            print(
                f"web {name}: clip={cam['clip']} t={cam['clipTime']:.3f}s ready in {time.time() - t0:.0f}s",
                flush=True,
            )
            pg.close()
        b.close()
    srv.shutdown()
    tmp.cleanup()
    (out / "poses.json").write_text(json.dumps({"size": SIZE, "poses": meta}, indent=1))


# aether.js keeps its renderer and look target private and stays byte-identical, so the harness
# rebuilds what it needs from the hooks it does expose (__cam, __root): the look point from the
# camera direction, and a second WebGLRenderer on the page's own canvas for the mask pass.
_GRAB_INTERNALS = """async () => { const THREE = await import('three'); window.__V3 = THREE.Vector3;
  const c = window.__cam, d = c.getWorldDirection(new THREE.Vector3());
  const box = new THREE.Box3().setFromObject(window.__root); const ctr = box.getCenter(new THREE.Vector3());
  window.__look = c.position.clone().add(d.multiplyScalar(c.position.distanceTo(ctr)));
  if (!window.__renderer) { const cv = document.querySelector('canvas');
    window.__renderer = new THREE.WebGLRenderer({ canvas: cv, context: cv.getContext('webgl2'), preserveDrawingBuffer: true });
    window.__renderer.setPixelRatio(devicePixelRatio); window.__renderer.setSize(innerWidth, innerHeight, false); }
  return true; }"""

QML = """import QtQuick
import QtQuick3D
import "%(conv)s"
Item {
    id: root
    width: %(w)d; height: %(h)d
    View3D {
        x: %(vx)d; y: 0; width: %(vw)d; height: parent.height
        environment: SceneEnvironment { clearColor: "#14101c"; backgroundMode: SceneEnvironment.Color; antialiasingMode: SceneEnvironment.MSAA }
        PerspectiveCamera { id: cam; objectName: "cam"; clipNear: 1; clipFar: 20000; fieldOfView: %(fov)f; fieldOfViewOrientation: PerspectiveCamera.Vertical }
        DirectionalLight { eulerRotation.x: -30; eulerRotation.y: 20; brightness: 1.2 }
        DirectionalLight { eulerRotation.x: -10; eulerRotation.y: 200; brightness: 0.5; color: "#b9a6ff" }
        PointLight { position: Qt.vector3d(0, 150, 200); brightness: 0.6 }
        Ellah_anim { id: ellah; objectName: "ellah"; scale: Qt.vector3d(100, 100, 100) }
    }
    function pose(clip, ms, pos, look) {
        var d = ellah.data
        for (var i = 0; i < d.length; i++) if (d[i].objectName && d[i].animations !== undefined) {
            d[i].animations[0].running = false; d[i].enabled = d[i].objectName === clip
            if (d[i].enabled) d[i].currentFrame = ms %% d[i].endFrame }
        cam.position = pos; cam.lookAt(look)
        return true
    }
}
"""


def run_qq3d(out: Path, qml_dir: Path) -> None:
    os.environ.setdefault("QSG_RHI_BACKEND", "opengl")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication, QSurfaceFormat, QVector3D
    from PySide6.QtQuick import QQuickView
    from PySide6.QtQuick3D import QQuick3D

    meta = json.loads((out / "poses.json").read_text())
    w, h = meta["size"]
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    QSurfaceFormat.setDefaultFormat(QQuick3D.idealSurfaceFormat())
    for name, m in meta["poses"].items():
        cam = m["camera"]
        src = out / "_qq3d.qml"
        conv = (qml_dir / "converted").resolve().as_uri()
        off = round(
            m["pan"] * w
        )  # same off-axis shift as setViewOffset: a View3D 2*off wider, slid by off
        src.write_text(
            QML
            % {
                "conv": conv,
                "w": w,
                "h": h,
                "fov": cam["fov"],
                "vx": min(0, 2 * off),
                "vw": w + 2 * abs(off),
            }
        )
        v = QQuickView()
        v.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        v.resize(w, h)
        v.setSource(QUrl.fromLocalFile(str(src)))
        if v.status() != QQuickView.Status.Ready:
            raise SystemExit("qq3d: " + "; ".join(e.toString() for e in v.errors()))
        v.show()
        s = 100.0  # metres (three.js) to the spike's scene units (model scaled by 100)
        ms = round((cam["clipTime"] or 0.0) * 1000)
        v.rootObject().pose(
            cam["clip"] or "Idle",
            ms,
            QVector3D(*[x * s for x in cam["pos"]]),
            QVector3D(*[x * s for x in cam["look"]]),
        )
        loop = QEventLoop()
        QTimer.singleShot(2500, loop.quit)
        loop.exec()
        img = v.grabWindow()
        img.save(str(out / f"qq3d-{name}.png"))
        print(
            f"qq3d {name}: clip={cam['clip']} frame={ms} rhi={v.rendererInterface().graphicsApi().name} {img.width()}x{img.height()}",
            flush=True,
        )
        v.close()
        v.deleteLater()
        app.processEvents()
    (out / "_qq3d.qml").unlink(missing_ok=True)


def region_masks(mask_png: Path, neck: list[float], head: list[float]):
    import numpy as np
    from PIL import Image, ImageFilter

    m = np.asarray(Image.open(mask_png).convert("RGB")).astype(int)
    body = (m[..., 0] > 128) & (m[..., 1] < 100)
    hair = m[..., 1] > 128
    parts = m[..., 2] > 128
    yy, xx = np.mgrid[0 : m.shape[0], 0 : m.shape[1]]
    hr = max(12.0, 1.6 * abs(neck[1] - head[1]))
    near_head = (xx - head[0]) ** 2 + (yy - head[1]) ** 2 < hr * hr
    face = ((body & (yy < neck[1])) | parts) & near_head & ~hair
    body = body & ~face
    sil = body | hair | face

    def grow(a, px: int):
        im = Image.fromarray((a * 255).astype("uint8"))
        return np.asarray(im.filter(ImageFilter.MaxFilter(2 * px + 1))) > 0

    def shrink(a, px: int):
        im = Image.fromarray((a * 255).astype("uint8"))
        return np.asarray(im.filter(ImageFilter.MinFilter(2 * px + 1))) > 0

    rim = grow(sil, 4) & ~shrink(sil, 4)
    halo = grow(sil, 48) & ~grow(sil, 4)
    out = {"face": face & ~rim, "hair": hair & ~rim, "body": body & ~rim, "rim": rim, "halo": halo}
    out["background"] = ~grow(sil, 48)
    return out


def compare(out: Path) -> dict[str, dict[str, dict[str, float]]]:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    meta = json.loads((out / "poses.json").read_text())
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
        small = ImageFont.truetype("DejaVuSans.ttf", 20)
    except OSError:
        font = small = ImageFont.load_default()
    colours = {
        "face": (255, 200, 0),
        "hair": (0, 220, 120),
        "body": (255, 60, 60),
        "rim": (0, 200, 255),
        "halo": (200, 80, 255),
    }
    results: dict[str, dict[str, dict[str, float]]] = {}
    thumbs = []
    for name, m in meta["poses"].items():
        a = np.asarray(Image.open(out / f"v14k-{name}.png").convert("RGB")).astype(float)
        bim = Image.open(out / f"qq3d-{name}.png").convert("RGB").resize((a.shape[1], a.shape[0]))
        b = np.asarray(bim).astype(float)
        d = np.sqrt(((a - b) ** 2).sum(-1) / 3.0)
        regs = region_masks(out / f"mask-{name}.png", m["neck"], m["head"])
        res = {}
        for r in REGIONS:
            k = regs[r]
            n = int(k.sum())
            res[r] = {
                "mean": round(float(d[k].mean()), 2) if n else 0.0,
                "over30_pct": round(100.0 * float((d[k] > 30).mean()), 2) if n else 0.0,
                "px": n,
            }
        for r, (lim_mean, lim_pct) in LIMITS.items():
            res[r]["pass"] = res[r]["mean"] < lim_mean and (
                lim_pct is None or res[r]["over30_pct"] < lim_pct
            )
        results[name] = res
        heat = np.zeros_like(a)
        heat[..., 0] = np.clip(d * 3, 0, 255)
        heat[..., 1] = np.clip(d * 3 - 255, 0, 255)
        heat[..., 2] = np.clip(d * 3 - 510, 0, 255)
        heat_im = Image.fromarray(heat.astype("uint8"))
        outline = Image.fromarray(a.astype("uint8")).copy()
        ov = np.asarray(outline).copy()
        for r, c in colours.items():  # 45% colour fill per region so the masks read at a glance
            ov[regs[r]] = (0.55 * ov[regs[r]] + 0.45 * np.array(c)).astype("uint8")
        wd, ht = a.shape[1], a.shape[0]
        sheet = Image.new("RGB", (wd * 4 + 30, ht + 150), (24, 24, 28))
        for i, (im, label) in enumerate(
            (
                (Image.fromarray(a.astype("uint8")), "v14k (three.js, SwiftShader)"),
                (bim, "Qt Quick 3D candidate (llvmpipe)"),
                (heat_im, "diff heat map (x3)"),
                (
                    Image.fromarray(ov),
                    "masks: face yellow, hair green, body red, rim cyan, halo violet",
                ),
            )
        ):
            sheet.paste(im, (i * (wd + 10), 40))
            ImageDraw.Draw(sheet).text(
                (i * (wd + 10) + 8, 8), label, fill=(235, 235, 235), font=font
            )
        dr = ImageDraw.Draw(sheet)
        line = "   ".join(
            f"{r} {res[r]['mean']:.1f} / {res[r]['over30_pct']:.0f}%" for r in REGIONS
        )
        dr.text(
            (8, ht + 52),
            f"pose {name}  clip {m['camera']['clip']} @ {m['camera']['clipTime']:.2f}s  size {wd}x{ht}",
            fill=(235, 235, 235),
            font=font,
        )
        dr.text(
            (8, ht + 92), "mean dRGB / pixels over 30:   " + line, fill=(200, 200, 200), font=small
        )
        sheet.save(out / f"sheet-{name}.png")
        th = Image.new("RGB", (wd + wd + 10, ht + 40), (24, 24, 28))
        th.paste(Image.fromarray(a.astype("uint8")), (0, 40))
        th.paste(bim, (wd + 10, 40))
        ImageDraw.Draw(th).text((8, 8), f"{name}: v14k | qq3d", fill=(235, 235, 235), font=font)
        thumbs.append(th.resize((th.width // 2, th.height // 2)))
    tw, thh = thumbs[0].size
    allsheet = Image.new("RGB", (tw * 3 + 20, thh * 2 + 10), (12, 12, 14))
    for i, t in enumerate(thumbs):
        allsheet.paste(t, ((i % 3) * (tw + 10), (i // 3) * (thh + 10)))
    allsheet.save(out / "sheet-all.png")
    (out / "diff.json").write_text(json.dumps(results, indent=1))
    print("pose        " + "".join(f"{r:>18}" for r in REGIONS))
    for name, res in results.items():
        print(
            f"{name:<12}"
            + "".join(f"{res[r]['mean']:>9.1f} {res[r]['over30_pct']:>6.1f}%  " for r in REGIONS)
        )
    return results


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("cmd", choices=("web", "qq3d", "compare", "all"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--glb", type=Path, default=PRIVATE / "models" / "ellah.glb")
    ap.add_argument("--clips", type=Path, default=PRIVATE / "ellah-anim.glb")
    ap.add_argument("--qml-dir", type=Path, help="folder holding the balsam output as converted/")
    ap.add_argument(
        "--qt-python", default=sys.executable, help="interpreter with PySide6 QtQuick3D (all)"
    )
    a = ap.parse_args()
    if a.cmd == "web":
        run_web(a.out, a.glb.resolve(), a.clips.resolve())
    elif a.cmd == "qq3d":
        if not a.qml_dir:
            ap.error("--qml-dir is required")
        run_qq3d(a.out, a.qml_dir)
    elif a.cmd == "compare":
        compare(a.out)
    else:
        if not a.qml_dir:
            ap.error("--qml-dir is required")
        me = str(Path(__file__).resolve())
        run_web(a.out, a.glb.resolve(), a.clips.resolve())
        subprocess.run(
            [
                "xvfb-run",
                "-a",
                "-s",
                "-screen 0 1920x1200x24",
                a.qt_python,
                me,
                "qq3d",
                "--out",
                str(a.out),
                "--qml-dir",
                str(a.qml_dir),
            ],
            check=True,
        )
        compare(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
