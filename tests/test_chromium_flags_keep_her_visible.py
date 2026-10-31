"""Her view is kept out of Windows native occlusion, set before QtWebEngine starts.

Babbage, 4d5ef87: she drew after a resize settled and went blank about 5 s
later at the same size; minimize/restore flipped her within 300 ms.
"""

from __future__ import annotations

import inspect


def test_flags_merge_with_existing_ones_and_are_set_before_qt_starts() -> None:
    from arelis.ui import launch
    from arelis.ui.persona_face import chromium_flags

    env = {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --disable-features=Foo,Bar"}
    chromium_flags.apply(env)
    parts = env["QTWEBENGINE_CHROMIUM_FLAGS"].split()
    assert "--disable-gpu" in parts
    assert "--disable-backgrounding-occluded-windows" in parts
    assert "--disable-renderer-backgrounding" in parts
    features = [p for p in parts if p.startswith("--disable-features=")]
    assert features == ["--disable-features=Foo,Bar,CalculateNativeWinOcclusion"]
    chromium_flags.apply(env)  # a second call adds nothing
    assert env["QTWEBENGINE_CHROMIUM_FLAGS"].split() == parts

    src = inspect.getsource(launch.run_ui)
    assert src.index("chromium_flags.apply()") < src.index("QApplication([])")
