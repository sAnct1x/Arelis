"""Her clips are fetched when anim.js loads, before the GLB and the animator.

Babbage, 9434a47: the clips landed 352 ms after ready (was 30) because the
fetches started only once the GLB was in and queued behind the first shader
compiles.
"""

from __future__ import annotations

import re

from arelis.ui.persona_face.web_avatar import WEB_DIR


def test_clips_are_fetched_before_the_animator_is_built() -> None:
    src = (WEB_DIR / "anim.js").read_text(encoding="utf-8")
    head, _, body = src.partition("export function createAnimator(")
    assert body, "createAnimator moved"
    assert re.search(r"clipJson\(GESTURE_CLIP\)", head)
    assert "fetch(" not in body, "a clip is still fetched inside createAnimator"
