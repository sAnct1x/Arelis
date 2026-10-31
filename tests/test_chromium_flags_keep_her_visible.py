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


def test_gpu_arm_defaults_to_d3d11_and_none_adds_nothing() -> None:
    from arelis.ui.persona_face import chromium_flags

    expected = {
        None: {"--use-angle=d3d11"},
        "default": {"--use-angle=d3d11"},
        "none": set(),
        "d3d11": {"--use-angle=d3d11"},
        "gl": {"--use-angle=gl"},
        "nocomp": {"--disable-gpu-compositing"},
        "bogus": {"--use-angle=d3d11"},
    }
    extra = {"--use-angle=d3d11", "--use-angle=gl", "--disable-gpu-compositing"}
    for name, want in expected.items():
        env = {} if name is None else {"ARELIS_GPU_ARM": name}
        parts = set(chromium_flags.apply(env).split())
        assert parts & extra == want, name
        assert "--disable-renderer-backgrounding" in parts
        assert chromium_flags.effective_arm(env) == ("none" if not want else min(want).split("=")[-1].replace("--disable-gpu-compositing", "nocomp")), name
    pinned = {"QTWEBENGINE_CHROMIUM_FLAGS": "--use-angle=gl"}
    assert set(chromium_flags.apply(pinned).split()) & extra == {"--use-angle=gl"}
    assert chromium_flags.effective_arm(pinned) == "gl"
