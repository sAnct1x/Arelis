"""Avatar CPU headroom: on by default; explicit false keeps today's launch line."""

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


def test_avatar_headroom_on_by_default_and_false_keeps_todays_launch_line(
    monkeypatch,
) -> None:
    monkeypatch.setattr(llama_launch, "_physical_cores", lambda: 8)
    off = _args({"avatar_headroom": False})
    # Today's original launch line, byte-identical.
    assert (
        off
        == (
            "llama-server -m m.gguf --mmproj p.gguf -ngl 99 -fa off -c 32768 -np 1 "
            "--n-cpu-moe 32 -ub 512 -b 4096 --cache-type-k f16 --cache-type-v f16 "
            "--image-max-tokens 1024 --jinja --chat-template-file t.jinja "
            "--host 127.0.0.1 --port 8080"
        ).split()
    )
    on = _args({})
    assert _args({"avatar_headroom": True}) == on
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


def test_restore_uses_saved_command_and_detaches_on_windows(monkeypatch) -> None:
    saved = [
        "llama-server",
        "-m",
        "model.gguf",
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
    ]

    class _Proc:
        pid = 4242

        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        llama_launch, "_cmdline_for_pid", lambda pid: list(saved) if pid == 4242 else None
    )
    monkeypatch.setattr(llama_launch, "_health_ok", lambda url: False)
    llama_launch._saved_args = None
    llama_launch._proc = _Proc()
    assert llama_launch.stop_server("http://127.0.0.1:8080") is True
    assert llama_launch.restore_args({}) == saved
    assert "--threads" not in llama_launch.restore_args({})

    seen: dict = {}

    class _Spawned:
        pid = 1

        def poll(self) -> int | None:
            return None

    def fake_popen(args, **kwargs):
        seen["args"] = list(args)
        seen.update(kwargs)
        return _Spawned()

    monkeypatch.setattr(llama_launch, "_log_path", lambda: None)
    monkeypatch.setattr(llama_launch.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    llama_launch._proc = None
    llama_launch.start_server_nowait(
        "http://127.0.0.1:8080", llama_launch.restore_args({})
    )
    assert seen["args"] == saved
    flags = int(seen["creationflags"])
    assert flags & 0x00000008  # DETACHED_PROCESS
    assert flags & 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
