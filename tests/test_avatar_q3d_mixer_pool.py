"""Quick 3D mixer: listening shares no clip with idle, so entering listening always starts a crossfade."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtQml import QJSEngine

MIXER = Path(__file__).resolve().parents[1] / "arelis/ui/persona_q3d/mixer.js"
CLIPS = [
    "Idle",
    "WeightShift",
    "v2_BreathingIdle",
    "v2_HappyIdle",
    "Talking",
    "Agreeing",
    "v2_ThoughtfulHeadNod",
    "Listening",
]


def test_listening_pool_has_no_idle_clip_so_entering_listening_always_fades(qt_app) -> None:
    js = QJSEngine()
    src = MIXER.read_text(encoding="utf-8").replace(".pragma library", "", 1)
    js.evaluate(src)
    durs = "{" + ",".join(f"{c}: 10" for c in CLIPS) + "}"
    for seed in range(20):
        r = js.evaluate(
            f"var m = create({durs}, {seed}); m.setState('idle'); for (var i = 0; i <= {seed}; i++) m.step(0.5);"
            "m.setState('listening'); var b = m.step(0.03), n = 0;"
            "while (POOLS.listening.indexOf(b.cur.name) < 0 && n++ < 40) b = m.step(0.03);"  # a running fade ends first
            "JSON.stringify([POOLS.listening.indexOf(b.cur.name) >= 0, b.prev ? b.prev.name : '', b.w])"
        )
        assert not r.isError(), r.toString()
        in_listen, prev, w = json.loads(r.toString())
        assert in_listen and prev in CLIPS[:4] and 0 < w < 1
