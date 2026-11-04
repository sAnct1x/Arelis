"""Her page logs Chromium's view of her visibility, so a blank shot can be explained.

Babbage, 4d5ef87: she went blank at a steady size; the log had nothing to
say whether Chromium thought her hidden or occluded at that moment.
"""

from __future__ import annotations

import re

from arelis.ui.persona_face.web_avatar import WEB_DIR


def test_visibility_changes_and_stalls_are_logged_with_the_state() -> None:
    src = (WEB_DIR / "aether.js").read_text(encoding="utf-8")
    assert re.search(r"addEventListener\('visibilitychange'.*\[avatar\] visibility ", src)
    assert "'state=' + document.visibilityState + ' hidden=' + document.hidden" in src
    stall = src[src.index("[avatar] frame stall") :].split("\n", 1)[0]
    assert "document.visibilityState" in stall
    assert "[avatar] heartbeat" in src


def test_a_resize_never_leaves_her_canvas_cleared_until_the_next_frame() -> None:
    """setSize clears the canvas; a grab before the next RAF caught her blank (capture-ab)."""
    src = (WEB_DIR / "aether.js").read_text(encoding="utf-8")
    assert re.search(r"addEventListener\('resize', \(\) => \{ if \(fitView\(\) && window\.__ready\) safeRender\(", src)
    # Every draw goes through the guarded, counted render; a thrown frame keeps the last one.
    assert src.count("composer.render()") == 1
    assert re.search(r"function frame\(dt\) \{\n  try \{ frameBody\(dt\); \} catch", src)
    heartbeat = src[src.index("[avatar] heartbeat") :].split("\n", 1)[0]
    assert "calls/frame=" in heartbeat and "zero=" in heartbeat and "errors=" in heartbeat
