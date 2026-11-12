"""Avatar CPU headroom: on by default; explicit false keeps today's launch line."""

from __future__ import annotations

import subprocess

from arelis.llm import llama_launch
from arelis.llm.llama_launch import llama_server_args, slot_save_dir


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
    # Built launch line, including --slot-save-path under the Arelis data folder.
    expected = [
        *(
            "llama-server -m m.gguf --mmproj p.gguf -ngl 99 -fa off -c 32768 -np 1 "
            "--n-cpu-moe 32 -ub 512 -b 4096 --cache-type-k f16 --cache-type-v f16 "
            "--image-max-tokens 1024 --jinja --chat-template-file t.jinja "
            "--slot-save-path"
        ).split(),
        str(slot_save_dir()),
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
    ]
    assert off == expected
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
    llama_launch._saved_cwd = None
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

def test_spawn_retries_without_breakaway_when_the_job_forbids_it(monkeypatch) -> None:
    seen: list[int] = []

    class _Spawned:
        pid = 1

        def poll(self) -> int | None:
            return None

    def fake_popen(args, **kwargs):
        del args
        flags = int(kwargs.get("creationflags") or 0)
        seen.append(flags)
        if flags & 0x01000000:
            raise PermissionError(13, "Access is denied")
        return _Spawned()

    monkeypatch.setattr(llama_launch, "_log_path", lambda: None)
    monkeypatch.setattr(llama_launch.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    llama_launch._proc = None
    proc = llama_launch._spawn(["llama-server", "--host", "127.0.0.1", "--port", "8080"])
    assert proc.poll() is None
    assert len(seen) == 2
    assert seen[0] & 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
    assert not (seen[1] & 0x01000000)
    assert seen[1] & 0x00000008  # DETACHED_PROCESS still set


def test_restore_replays_saved_cwd_and_falls_back_with_a_message(
    tmp_path, monkeypatch
) -> None:
    from arelis.tools import gpu_lease

    work = tmp_path / "server-home"
    work.mkdir()
    saved = ["llama-server", "-m", "model.gguf", "--host", "127.0.0.1", "--port", "8080"]
    built = [
        "llama-server",
        "-m",
        str(tmp_path / "abs-model.gguf"),
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
    monkeypatch.setattr(
        llama_launch, "_cwd_for_pid", lambda pid: str(work) if pid == 4242 else None
    )
    monkeypatch.setattr(llama_launch, "_health_ok", lambda url: False)
    llama_launch._saved_args = None
    llama_launch._saved_cwd = None
    llama_launch._proc = _Proc()
    assert llama_launch.stop_server("http://127.0.0.1:8080") is True
    assert llama_launch.restore_args({}) == saved
    assert llama_launch.restore_cwd() == str(work)

    calls: list[tuple[list[str], str | None]] = []

    class _Dead:
        pid = 8

        def poll(self) -> int | None:
            return 1

    class _Live:
        pid = 9

        def poll(self) -> int | None:
            return None

    def fake_popen(args, **kwargs):
        calls.append((list(args), kwargs.get("cwd")))
        if list(args) == saved:
            return _Dead()
        return _Live()

    monkeypatch.setattr(llama_launch, "_log_path", lambda: None)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llama_launch, "launch_args_for", lambda config: list(built))
    monkeypatch.setattr(
        llama_launch, "_wait_ready", lambda url, proc, timeout: proc.poll() is None
    )
    llama_launch._proc = None
    llama_launch.ensure_server("http://127.0.0.1:8080", llama_launch.restore_args({}))
    assert calls[0] == (saved, str(work))
    assert calls[1] == (built, None)

    told: list[str] = []

    def boom(url: str, args: list[str] | None) -> None:
        del url, args
        raise RuntimeError("could not start")

    gpu_lease.reset_for_tests(
        stop=lambda url: True,
        ensure=boom,
        nowait=boom,
        args=lambda _config: list(saved),
    )
    gpu_lease.set_status(told.append)
    try:
        gpu_lease.acquire({"llamacpp": {"base_url": "http://127.0.0.1:8080"}})
        raised = False
        try:
            gpu_lease.release()
        except RuntimeError:
            raised = True
        assert raised is True
        assert gpu_lease.CHAT_RESTORE_FAILED in told
    finally:
        gpu_lease.reset_for_tests()
        llama_launch._saved_args = None
        llama_launch._saved_cwd = None


def test_lease_restore_uses_saved_command_not_built_args(monkeypatch) -> None:
    from arelis.tools import gpu_lease

    saved = ["llama-server", "-m", "kept.gguf", "--host", "127.0.0.1", "--port", "8080"]
    built = [
        "llama-server",
        "-m",
        "kept.gguf",
        "--threads",
        "4",
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
    ]
    seen: list[list[str]] = []

    def ensure(url: str, args: list[str] | None) -> None:
        del url
        seen.append(list(args or []))

    llama_launch._saved_args = list(saved)
    llama_launch._saved_cwd = None
    monkeypatch.setattr(llama_launch, "launch_args_for", lambda config: list(built))
    gpu_lease.reset_for_tests(
        stop=lambda url: True,
        ensure=ensure,
        nowait=lambda url, args: None,
    )
    try:
        gpu_lease.acquire({"llamacpp": {"base_url": "http://127.0.0.1:8080"}})
        gpu_lease.release()
        assert seen == [saved]
    finally:
        llama_launch._saved_args = None
        llama_launch._saved_cwd = None
        gpu_lease.reset_for_tests()


def test_ensure_fallback_keeps_configured_port_and_context(tmp_path, monkeypatch) -> None:
    from arelis.tools import gpu_lease

    model = tmp_path / "custom.gguf"
    model.write_bytes(b"gguf")
    binary = str(tmp_path / "custom-llama-server")
    config = {
        "llamacpp": {
            "base_url": "http://127.0.0.1:8090",
            "default_cap": 16384,
            "model": str(model),
            "binary": binary,
            "avatar_headroom": False,
        }
    }
    saved = [
        "llama-server",
        "-m",
        "model.gguf",
        "--host",
        "127.0.0.1",
        "--port",
        "8090",
    ]

    class _Dead:
        pid = 8

        def poll(self) -> int | None:
            return 1

    class _Live:
        pid = 9

        def poll(self) -> int | None:
            return None

    calls: list[list[str]] = []

    def fake_popen(args, **kwargs):
        del kwargs
        calls.append(list(args))
        if list(args) == saved:
            return _Dead()
        return _Live()

    # Weights are findable even with an empty config, so a reverted
    # launch_args_for(None) still builds a line and the wrong port/ctx fail.
    monkeypatch.setattr(llama_launch, "locate_model_gguf", lambda _config: model)
    monkeypatch.setattr(llama_launch, "_log_path", lambda: None)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llama_launch, "_health_ok", lambda url: False)
    monkeypatch.setattr(
        llama_launch, "_wait_ready", lambda url, proc, timeout: proc.poll() is None
    )
    llama_launch._saved_args = list(saved)
    llama_launch._saved_cwd = None
    llama_launch._proc = None
    gpu_lease.reset_for_tests(
        stop=lambda url: True,
        nowait=lambda url, args: None,
        args=lambda _config: list(saved),
    )
    try:
        gpu_lease.acquire(config)
        gpu_lease.release()
        assert len(calls) == 2
        assert calls[0] == saved
        fallback = calls[1]
        assert fallback[0] == binary
        assert fallback[fallback.index("--port") + 1] == "8090"
        assert fallback[fallback.index("-c") + 1] == "16384"
    finally:
        llama_launch._saved_args = None
        llama_launch._saved_cwd = None
        llama_launch._proc = None
        gpu_lease.reset_for_tests()
