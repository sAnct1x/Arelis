"""Her view is never hidden and re-shown as a repaint trick.

16ec85c hid and re-showed the web view's native child after every resize or
window-state change. On 4d5ef87 she still blanked 5 s after a settled resize,
and minimize/restore flipped her within 300 ms: hide/show is itself a
visibility flip for Chromium, so the trick fed the fault it was meant to cure.
"""

from __future__ import annotations

import inspect

from arelis.ui.persona_face import panel, web_avatar


def test_no_hide_show_rearm_of_her_surface() -> None:
    src = inspect.getsource(panel) + inspect.getsource(web_avatar)
    assert "rearm_surface" not in src
    assert "_REARM_MS" not in src
