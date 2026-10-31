"""Listening must look different from idle: its clip pool shares no clip with idle's."""

from __future__ import annotations

import re
from pathlib import Path

MIXER = Path(__file__).resolve().parents[1] / "arelis/ui/persona_face/web/anim-mixer.js"


def test_listening_pool_has_no_idle_clip_so_entering_listening_always_fades() -> None:
    src = MIXER.read_text(encoding="utf-8")
    pools = {
        k: set(re.findall(r"'(\w+)'", v))
        for k, v in re.findall(r"^\s+(\w+): \[([^\]]*)\]", src, re.M)
    }
    assert pools["listening"] and not pools["listening"] & pools["idle"]
