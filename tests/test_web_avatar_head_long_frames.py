"""The web avatar keeps her head in its designed sway when frames arrive slowly.

anim.js moved the head with Euler-stepped springs. After a stall, at 0.1 s per frame, the talking nod
spring rang out until her head swung far off to one side. Runs anim.js under node on a bare three.js
bone chain, so the private model is not needed.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from arelis.ui.persona_face.web_avatar import WEB_DIR

SCRIPT = """
const THREE = await import(%(three)s);
const { createAnimator } = await import(%(anim)s);
const root = new THREE.Object3D();
const mk = (n, p) => { const b = new THREE.Object3D(); b.name = n; p.add(b); return b; };
const neck = mk('CC_Base_NeckTwist01', root), head = mk('CC_Base_Head', neck);
for (const n of ['CC_Base_JawRoot', 'CC_Base_L_Eye', 'CC_Base_R_Eye']) mk(n, head);
const { update, api } = createAnimator(THREE, root, { visemes: [] }, { value: new THREE.Vector4() }, {});
api.setState('speaking');
const deg = (o) => 2 * Math.acos(Math.min(1, Math.abs(o.quaternion.w))) * 180 / Math.PI;
let worst = 0;
for (let i = 0; i < 100; i++) {
  api.setLevel(0.2 + 0.7 * Math.abs(Math.sin(i * 0.4)));
  update(0.1);
  const a = deg(head) + deg(neck);
  if (!(a <= worst)) worst = a;
}
console.log(JSON.stringify(worst));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_web_head_stays_in_range_at_a_slow_frame(tmp_path) -> None:
    script = tmp_path / "head.mjs"
    script.write_text(
        SCRIPT
        % {
            "three": json.dumps((WEB_DIR / "vendor" / "three" / "three.module.min.js").as_uri()),
            "anim": json.dumps((WEB_DIR / "anim.js").as_uri()),
        },
        encoding="utf-8",
    )
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) < 20  # head plus neck, degrees
