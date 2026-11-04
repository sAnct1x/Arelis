"""Export the live v14k aether scene (layer geometry, shaders, uniforms) for the Quick 3D port.

Runs the three.js page headless, the same way tools/avatar_lookmatch.py does, and writes:
  layers.json      one entry per drawn object: kind, flags, attribute files, shader strings
  <name>.bin       raw little-endian attribute and index buffers
  tex_<n>.png      alpha maps used by hair, brow and lash cards
  uniforms.json    per pose, every layer's uniform values at the captured frame

The output is derived from the private model, so it belongs outside the repo
(default /workspace/team/avatar-qq3d/scene). aether.js is only read, never changed.
"""
# ruff: noqa: E501  (embedded JS reads better unwrapped)

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import avatar_lookmatch as lm

DUMP_JS = r"""
async () => {
  const THREE = await import('three');
  const scene = window.__root.parent; scene.updateMatrixWorld(true);
  const objs = []; scene.traverse((o) => { if ((o.isMesh || o.isPoints) && o.visible) objs.push(o); });
  window.__q3dObjs = objs;
  const enc = (arr) => { const u8 = new Uint8Array(arr.buffer, arr.byteOffset, arr.byteLength); let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); };
  const texs = new Map(); const texData = [];
  const texId = (t) => { if (!texs.has(t)) { const im = t.image; const c = document.createElement('canvas'); c.width = im.width; c.height = im.height; const cx = c.getContext('2d'); if (im.data) { const n = im.width * im.height, ch = im.data.length / n, id = cx.createImageData(im.width, im.height), f = im.data instanceof Float32Array ? 255 : 1; for (let j = 0; j < n; j++) for (let k = 0; k < 4; k++) id.data[4 * j + k] = k < ch ? im.data[ch * j + k] * f : (k === 3 ? 255 : im.data[ch * j] * f); cx.putImageData(id, 0, 0); } else cx.drawImage(im, 0, 0); texs.set(t, texData.length); texData.push(c.toDataURL('image/png')); } return texs.get(t); };
  const geoms = new Map(); const bufs = {};
  const out = objs.map((o, i) => {
    const g = o.geometry, m = o.material;
    if (!geoms.has(g)) { const id = 'g' + geoms.size; const at = {};
      for (const [k, a] of Object.entries(g.attributes)) { const f = new Float32Array(a.count * a.itemSize); for (let j = 0; j < a.count; j++) for (let c = 0; c < a.itemSize; c++) f[j * a.itemSize + c] = a.getComponent(j, c); bufs[id + '_' + k] = enc(f); at[k] = a.itemSize; }
      let count = g.attributes.position.count, idx = 0; if (g.index) { bufs[id + '_index'] = enc(new Uint32Array(g.index.array)); idx = g.index.count; }
      geoms.set(g, { id, at, count, idx }); }
    let par = o.parent, bone = null; while (par) { if (par.isBone) { bone = par.name; break; } par = par.parent; }
    const ref = m.uniforms && m.uniforms.boneTex ? objs.find((r) => r.isSkinnedMesh && r.skeleton.boneTexture === m.uniforms.boneTex.value && r.bindMatrix === m.uniforms.bindM.value) : null;
    const so = o.isSkinnedMesh ? o : ref;   // aether.js skinPoint layers borrow a body mesh's skeleton (skinUniforms(ref))
    const sk = so ? { bones: so.skeleton.bones.map((b) => b.name), bind: so.bindMatrix.toArray(), inv: so.skeleton.boneInverses.map((b) => b.toArray()), ref: ref ? objs.indexOf(ref) : null } : null;
    return { i, type: o.type, name: o.name, parent: o.parent && o.parent.name, ro: o.renderOrder, world: o.matrixWorld.toArray(), geom: geoms.get(g), skin: sk,
      mat: { type: m.type, blend: m.blending, dt: m.depthTest, dw: m.depthWrite, cw: m.colorWrite, tr: m.transparent, side: m.side, opacity: m.opacity, alphaTest: m.alphaTest,
        color: m.color ? m.color.toArray() : null, size: m.size, alphaMap: m.alphaMap ? texId(m.alphaMap) : null,
        vs: m.vertexShader || null, fs: m.fragmentShader || null,
        utex: m.uniforms ? Object.fromEntries(Object.entries(m.uniforms).filter(([k, u]) => u.value && u.value.isTexture && k !== 'boneTex').map(([k, u]) => [k, texId(u.value)])) : {} } };
  });
  return { layers: out, bufs, texData, chunks: { } };
}
"""

UNIFORMS_JS = r"""
() => { const val = (v) => v === null || v === undefined ? null : typeof v === 'number' || typeof v === 'boolean' ? +v : v.isTexture ? null : v.isMatrix4 ? null : v.isColor ? v.toArray() : (v.isVector2 || v.isVector3 || v.isVector4) ? v.toArray() : Array.isArray(v) ? v.map(val) : null;
  const objs = []; window.__root.parent.traverse((o) => { if ((o.isMesh || o.isPoints) && o.visible) objs.push(o); });
  return objs.map((o) => { const m = o.material; const u = {}; if (m.uniforms) for (const [k, x] of Object.entries(m.uniforms)) { const v = val(x.value); if (v !== null) u[k] = v; } return u; }); }
"""

WORLD_JS = r"""
() => { const objs = []; window.__root.parent.traverse((o) => { if ((o.isMesh || o.isPoints) && o.visible) objs.push(o); });
  const w = {}; objs.forEach((o, i) => { if (!o.isSkinnedMesh) w[i] = o.matrixWorld.toArray(); }); return w; }
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("/workspace/team/avatar-qq3d/scene"))
    ap.add_argument("--glb", type=Path, default=lm.PRIVATE / "models/ellah.glb")
    ap.add_argument("--anim", type=Path, default=lm.PRIVATE / "ellah-anim.glb")
    args = ap.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    unis: dict[str, list] = {}
    worlds: dict[str, dict] = {}

    def on_pose(page, pose):
        if not hasattr(on_pose, "done"):
            on_pose.done = True
            d = page.evaluate(DUMP_JS)
            for k, b64 in d["bufs"].items():
                (out / f"{k}.bin").write_bytes(base64.b64decode(b64))
            for n, url in enumerate(d["texData"]):
                (out / f"tex_{n}.png").write_bytes(base64.b64decode(url.split(",", 1)[1]))
            (out / "layers.json").write_text(json.dumps(d["layers"], indent=1))
        unis[pose] = page.evaluate(UNIFORMS_JS)
        worlds[pose] = page.evaluate(WORLD_JS)

    lm.run_web(out / "web", args.glb, args.anim, on_pose=on_pose)
    (out / "uniforms.json").write_text(json.dumps(unis))
    (out / "worlds.json").write_text(json.dumps(worlds))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
