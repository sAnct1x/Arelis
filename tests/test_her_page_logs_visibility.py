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
