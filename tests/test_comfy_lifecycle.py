"""ComfyUI auto-start: probe, launch once, wait for health."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools import comfy_lifecycle as life


def test_resolve_launch_from_main_py_directory(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("# comfy\n", encoding="utf-8")
    resolved = life.resolve_launch(
        launch_command="",
        launch_cwd=str(tmp_path),
        comfy_url="http://127.0.0.1:8188",
    )
    assert resolved is not None
    argv, cwd = resolved
    assert cwd == tmp_path.resolve()
    assert argv[-4:] == ["--listen", "127.0.0.1", "--port", "8188"]
    assert argv[-5].endswith("main.py")


def test_resolve_launch_prefers_bat_when_no_main(tmp_path: Path) -> None:
    bat = tmp_path / "run_cpu.bat"
    bat.write_text("@echo off\n", encoding="utf-8")
    resolved = life.resolve_launch(
        launch_command="",
        launch_cwd=str(tmp_path),
        comfy_url="http://127.0.0.1:8188",
    )
    assert resolved is not None
    argv, cwd = resolved
    assert cwd == tmp_path.resolve()
    assert argv[:2] == ["cmd", "/c"]
    assert argv[2:6] == ["start", "", "/b", "/wait"]
    assert argv[6] == str(bat.resolve())


def test_resolve_launch_uses_main_with_directml_flag(tmp_path: Path) -> None:
    """Bat beside the tree means DirectML — but launch python, not the console bat."""
    (tmp_path / "main.py").write_text("# comfy\n", encoding="utf-8")
    (tmp_path / "run_directml.bat").write_text("@echo off\n", encoding="utf-8")
    resolved = life.resolve_launch(
        launch_command="",
        launch_cwd=str(tmp_path),
        comfy_url="http://127.0.0.1:8188",
    )
    assert resolved is not None
    argv, cwd = resolved
    assert cwd == tmp_path.resolve()
    assert argv[0].endswith("python.exe") or "python" in Path(argv[0]).name.lower()
    assert argv[-1] == "--directml" or "--directml" in argv
    assert any(str(a).endswith("main.py") for a in argv)


def test_resolve_launch_prefers_venv_directml_over_embed(tmp_path: Path) -> None:
    """AMD DirectML path must not use python_embeded (ROCm AV on cuda probe)."""
    (tmp_path / "main.py").write_text("# comfy\n", encoding="utf-8")
    (tmp_path / "run_directml.bat").write_text("@echo off\n", encoding="utf-8")
    embed = tmp_path / "python_embeded"
    embed.mkdir()
    (embed / "python.exe").write_bytes(b"")
    venv = tmp_path / "venv_directml" / "Scripts"
    venv.mkdir(parents=True)
    (venv / "python.exe").write_bytes(b"")
    resolved = life.resolve_launch(
        launch_command="",
        launch_cwd=str(tmp_path),
        comfy_url="http://127.0.0.1:8188",
    )
    assert resolved is not None
    argv, _cwd = resolved
    assert "venv_directml" in argv[0].replace("\\", "/")
    assert "python_embeded" not in argv[0]
    assert "--directml" in argv


def test_resolve_launch_ignores_bat_command_when_main_exists(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("# comfy\n", encoding="utf-8")
    bat = tmp_path / "run_directml.bat"
    bat.write_text("@echo off\n", encoding="utf-8")
    venv = tmp_path / "venv_directml" / "Scripts"
    venv.mkdir(parents=True)
    (venv / "python.exe").write_bytes(b"")
    resolved = life.resolve_launch(
        launch_command=str(bat),
        launch_cwd=str(tmp_path),
        comfy_url="http://127.0.0.1:8188",
    )
    assert resolved is not None
    argv, _cwd = resolved
    assert argv[:2] != ["cmd", "/c"]
    assert "--directml" in argv
    assert "venv_directml" in argv[0].replace("\\", "/")


def test_resolve_launch_returns_none_when_unconfigured() -> None:
    assert (
        life.resolve_launch(
            launch_command="",
            launch_cwd="",
            comfy_url="http://127.0.0.1:8188",
        )
        is None
    )


@pytest.mark.asyncio
async def test_ensure_skips_launch_when_already_healthy(monkeypatch) -> None:
    async def healthy(url, **kwargs):
        return True

    monkeypatch.setattr(life, "comfy_is_healthy_async", healthy)
    started = {"n": 0}

    def boom(*args, **kwargs):
        started["n"] += 1
        raise AssertionError("should not start")

    monkeypatch.setattr(life, "start_comfy", boom)
    err = await life.ensure_comfy_running(
        "http://127.0.0.1:8188",
        launch_cwd="C:/does/not/matter",
        auto_start=True,
    )
    assert err is None
    assert started["n"] == 0


@pytest.mark.asyncio
async def test_ensure_explains_missing_launch_cwd(monkeypatch) -> None:
    async def down(url, **kwargs):
        return False

    monkeypatch.setattr(life, "comfy_is_healthy_async", down)
    err = await life.ensure_comfy_running(
        "http://127.0.0.1:8188",
        launch_cwd="",
        launch_command="",
        auto_start=True,
    )
    assert err is not None
    assert "launch_cwd" in err


def test_format_exit_code_access_violation() -> None:
    text = life._format_exit_code(3221225477)
    assert "0xC0000005" in text
    assert "3221225477" in text


@pytest.mark.asyncio
async def test_ensure_starts_and_waits(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "main.py").write_text("# comfy\n", encoding="utf-8")
    calls = {"health": 0, "start": 0}

    async def health(url, **kwargs):
        calls["health"] += 1
        return calls["health"] >= 3

    def start(argv, cwd):
        calls["start"] += 1

        class Proc:
            def poll(self):
                return None

        life._process = Proc()  # type: ignore[assignment]
        return life._process

    monkeypatch.setattr(life, "comfy_is_healthy_async", health)
    monkeypatch.setattr(life, "start_comfy", start)

    err = await life.ensure_comfy_running(
        "http://127.0.0.1:8188",
        launch_cwd=str(tmp_path),
        startup_timeout_s=5,
        auto_start=True,
    )
    assert err is None
    assert calls["start"] == 1
    life._process = None


def test_start_comfy_hides_console_not_detached(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}

    class FakeProc:
        def poll(self):
            return None

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(life.subprocess, "Popen", fake_popen)
    life._process = None
    life._log_handle = None
    life.start_comfy(["python", "main.py"], tmp_path)
    flags = int(captured.get("creationflags") or 0)
    no_window = getattr(life.subprocess, "CREATE_NO_WINDOW", 0)
    detached = getattr(life.subprocess, "DETACHED_PROCESS", 0)
    assert flags & no_window
    assert not (flags & detached)
    life._process = None
    if life._log_handle is not None:
        try:
            life._log_handle.close()
        except Exception:
            pass
        life._log_handle = None
