"""Avatar CPU headroom: llama-server gets fewer threads only when the setting is on."""

from __future__ import annotations

import subprocess

from arelis.llm import llama_launch
from arelis.llm.llama_launch import llama_server_args


def _args(lc: dict) -> list[str]:
    return llama_server_args(
        binary="llama-server",
        model="m.gguf",
        mmproj="p.gguf",
        template="t.jinja",
        config={"llamacpp": lc},
    )


def test_avatar_headroom_leaves_two_cores_and_off_keeps_todays_launch_line(
    monkeypatch,
) -> None:
    monkeypatch.setattr(llama_launch, "_physical_cores", lambda: 8)
    off = _args({})
    assert _args({"avatar_headroom": False}) == off
    assert "--threads" not in off
    on = _args({"avatar_headroom": True})
    assert on[on.index("--threads") + 1] == "6"
    assert [a for a in on if a not in ("--threads", "6")] == off
    assert llama_launch.headroom_threads(2) == 1

    seen: dict = {}
    monkeypatch.setattr(llama_launch, "_log_path", lambda: None)
    monkeypatch.setattr(llama_launch.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "Popen", lambda a, **kw: seen.update(kw))
    llama_launch._spawn(on)
    assert seen["creationflags"] & 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
    llama_launch._spawn(off)
    assert not seen["creationflags"] & 0x00004000
