"""Her idle hip pose must not cost a frame budget: the hand-contact search prunes, with the same answer.

The contact solver asks for the signed distance from many hand samples to the hip skin every frame.
It scanned every near triangle per sample, about 45 ms a frame on the GPU run, so idle sat at 8-20 fps.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "persona_face" / "web"

HARNESS = r"""
import * as THREE from '%(three)s';
const V3 = () => new THREE.Vector3();
let __cc = 0;
%(code)s
let s = 7; const r = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
const n = 900, W = new Float32Array(n * 9), N = new Float32Array(n * 9), tri = new Int32Array(n * 3);
for (let t = 0; t < n; t++) { const cx = r() * 0.18 - 0.09, cy = r() * 0.18 - 0.09, cz = r() * 0.02;
  for (let k = 0; k < 3; k++) { const i = 3 * (3 * t + k); W[i] = cx + r() * 0.01; W[i + 1] = cy + r() * 0.01; W[i + 2] = cz + r() * 0.004;
    N[i] = r() - 0.5; N[i + 1] = r() - 0.5; N[i + 2] = 1; tri[3 * t + k] = 3 * t + k; } }
const C = { parts: [{ W, N, tri }] };
ctNear(C, new THREE.Vector3(0, 0, 0), 0.2);
const brute = (p) => { let best = 1e9, bc = V3(), fn = V3(); const tmp = V3(), a = V3(), b = V3(), c = V3();
  for (let t = 0; t < tri.length; t += 3) { a.fromArray(W, 3 * tri[t]); b.fromArray(W, 3 * tri[t + 1]); c.fromArray(W, 3 * tri[t + 2]);
    ctClosest(p, a, b, c, tmp); const d = tmp.distanceToSquared(p);
    if (d < best) { best = d; bc.copy(tmp); const i0 = 3 * tri[t], i1 = 3 * tri[t + 1], i2 = 3 * tri[t + 2]; fn.set(N[i0] + N[i1] + N[i2], N[i0 + 1] + N[i1 + 1] + N[i2 + 1], N[i0 + 2] + N[i1 + 2] + N[i2 + 2]); } }
  const dir = V3().subVectors(p, bc), d = Math.sqrt(best); fn.normalize(); const sg = dir.dot(fn) >= 0 ? 1 : -1; return { d: sg * d, n: d > 1e-6 ? dir.multiplyScalar(sg / d) : fn }; };
let same = 0, calls = 0; const Q = 300;
for (let k = 0; k < Q; k++) { const p = new THREE.Vector3(r() * 0.12 - 0.06, r() * 0.12 - 0.06, 0.004 + r() * 0.006);
  const before = __cc; const a = ctSD(C, p); calls += __cc - before; const b = brute(p);
  if (a.d === b.d && a.n.x === b.n.x && a.n.y === b.n.y && a.n.z === b.n.z) same++; }
console.log(JSON.stringify({ same, Q, perQuery: calls / Q, n }));
"""


def _contact_code() -> str:
    src = (WEB / "anim.js").read_text(encoding="utf-8")
    start = src.index("  const _cA = V3()")
    end = src.index("  const HIPANC =")
    code = src[start:end]
    hook = "function ctClosest(p, a, b, c, out) {"
    assert hook in code
    return code.replace(hook, hook + " __cc++;")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_contact_distance_prunes_triangles_and_keeps_the_answer(tmp_path) -> None:
    three = (WEB / "vendor" / "three" / "three.module.min.js").as_uri()
    script = tmp_path / "contact.mjs"
    script.write_text(HARNESS % {"three": three, "code": _contact_code()}, encoding="utf-8")
    out = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=60, check=True
    )
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert res["same"] == res["Q"]
    assert res["perQuery"] < res["n"] / 4
