"""Built-in sd.cpp image backend: lease, default, download cleanup, command line."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from arelis.tools import gpu_lease
from arelis.tools.image import ImageTool
from arelis.tools.image_models import ModelError
from arelis.tools.sdcpp import (
    NOT_YET,
    command_from_config,
    resolve_backend,
)
from arelis.workspace import RootEntry, WorkspaceRoots


def _png(path: Path, *, size: tuple[int, int] = (32, 32)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (40, 120, 80)).save(path, format="PNG")
    return path


def _files(tmp_path: Path) -> dict[str, Path]:
    folder = tmp_path / "sdcpp"
    folder.mkdir(parents=True, exist_ok=True)
    return {
        "binary": folder / "sd-cli.exe",
        "model": folder / "flux-2-klein-4b-Q4_0.gguf",
        "llm": folder / "Qwen3-4B-Q4_K_M.gguf",
        "vae": folder / "flux2-vae.safetensors",
    }


def _write_output(path: Path) -> None:
    _png(path)


@pytest.fixture(autouse=True)
def _reset_lease() -> None:
    from arelis.tools import sdcpp

    gpu_lease.reset_for_tests()
    sdcpp.reset_for_tests()
    yield
    gpu_lease.reset_for_tests()
    sdcpp.reset_for_tests()


def _install_lease_spies() -> list[tuple[Any, ...]]:
    events: list[tuple[Any, ...]] = []

    def stop(url: str) -> bool:
        events.append(("stop", url))
        return True

    def ensure(url: str, args: list[str] | None) -> None:
        events.append(("ensure", url, list(args or [])))

    def nowait(url: str, args: list[str] | None) -> None:
        events.append(("nowait", url, list(args or [])))

    gpu_lease.reset_for_tests(
        stop=stop,
        ensure=ensure,
        nowait=nowait,
        args=lambda _config: ["llama-server", "--host", "127.0.0.1", "--port", "8080"],
    )
    return events


def _patch_sdcpp_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    files = _files(tmp_path)

    def ensure_files(config: dict[str, Any] | None = None, *, cancelled=None):
        del config, cancelled
        return files

    def run_cli(args: list[str], output: Path, *, cancelled=None, **kwargs: Any) -> None:
        del args, kwargs
        if cancelled is not None and cancelled():
            from arelis.tools.sdcpp import GenerationCancelledError

            raise GenerationCancelledError()
        _write_output(output)

    monkeypatch.setattr("arelis.tools.image.ensure_files", ensure_files)
    monkeypatch.setattr("arelis.tools.image.run_cli", run_cli)
    monkeypatch.setattr(
        "arelis.tools.image.ImageTool._sdcpp_supported", lambda self: True
    )


def test_lease_stops_then_restores_llama_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _install_lease_spies()
    _patch_sdcpp_ready(monkeypatch, tmp_path)
    config = {
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
        "tools": {"image": {"backend": "sdcpp", "sdcpp": {"idle_timeout_s": 0}}},
    }
    tool = ImageTool(
        comfy_url="http://127.0.0.1:9",
        output_dir=str(tmp_path / "out"),
        backend="sdcpp",
        config=config,
    )
    result = asyncio.run(tool.run(prompt="a red fox"))
    assert result.ok is True
    assert [item[0] for item in events] == ["stop", "ensure"]
    assert events[0][1] == "http://127.0.0.1:8080"
    assert events[1][1] == "http://127.0.0.1:8080"


def test_lease_restores_llama_server_when_sdcpp_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _install_lease_spies()
    _patch_sdcpp_ready(monkeypatch, tmp_path)

    def run_cli(args: list[str], output: Path, *, cancelled=None, **kwargs: Any) -> None:
        del args, output, cancelled, kwargs
        raise RuntimeError("The picture program stopped before it finished.")

    monkeypatch.setattr("arelis.tools.image.run_cli", run_cli)
    config = {
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
        "tools": {"image": {"backend": "sdcpp"}},
    }
    tool = ImageTool(
        comfy_url="http://127.0.0.1:9",
        output_dir=str(tmp_path / "out"),
        backend="sdcpp",
        config=config,
    )
    result = asyncio.run(tool.run(prompt="a red fox"))
    assert result.ok is False
    assert "[fail:image]" in result.output
    assert [item[0] for item in events] == ["stop", "ensure"]


def test_lease_restores_llama_server_when_generation_is_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _install_lease_spies()
    _patch_sdcpp_ready(monkeypatch, tmp_path)
    held = {"stop": False}

    def stop(url: str) -> bool:
        held["stop"] = True
        events.append(("stop", url))
        return True

    gpu_lease.reset_for_tests(
        stop=stop,
        ensure=lambda url, args: events.append(("ensure", url, list(args or []))),
        nowait=lambda url, args: events.append(("nowait", url, list(args or []))),
        args=lambda _config: ["llama-server"],
    )
    config = {
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
        "tools": {"image": {"backend": "sdcpp"}},
    }
    tool = ImageTool(
        comfy_url="http://127.0.0.1:9",
        output_dir=str(tmp_path / "out"),
        backend="sdcpp",
        config=config,
    )
    tool.is_cancelled = lambda: held["stop"]
    result = asyncio.run(tool.run(prompt="a red fox"))
    assert result.ok is False
    assert "stopped" in result.output.lower()
    assert [item[0] for item in events] == ["stop", "ensure"]


def test_successful_run_restores_chat_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _install_lease_spies()
    _patch_sdcpp_ready(monkeypatch, tmp_path)
    config = {
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
        "tools": {"image": {"backend": "sdcpp", "sdcpp": {"idle_timeout_s": 90}}},
    }
    tool = ImageTool(
        comfy_url="http://127.0.0.1:9",
        output_dir=str(tmp_path / "out"),
        backend="sdcpp",
        config=config,
    )
    result = asyncio.run(tool.run(prompt="a red fox"))
    assert result.ok is True
    assert gpu_lease.is_generating() is False
    assert gpu_lease.is_held() is False
    assert [item[0] for item in events] == ["stop", "ensure"]


def test_quit_stops_in_flight_sdcli_before_starting_llama_server() -> None:
    from arelis.tools import sdcpp

    order: list[str] = []

    class _FakeProc:
        def __init__(self) -> None:
            self.pid = 4242
            self._code: int | None = None

        def poll(self) -> int | None:
            return self._code

        def terminate(self) -> None:
            order.append("stop-sdcli")
            self._code = 1

        def kill(self) -> None:
            order.append("kill-sdcli")
            self._code = 1

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            if self._code is None:
                raise subprocess.TimeoutExpired(cmd="sd-cli", timeout=0)
            return self._code

    def nowait(url: str, args: list[str] | None) -> None:
        del url, args
        order.append("start-llama")

    gpu_lease.reset_for_tests(
        stop=lambda url: True,
        ensure=lambda url, args: None,
        nowait=nowait,
        args=lambda _config: ["llama-server"],
    )
    gpu_lease.acquire({"llamacpp": {"base_url": "http://127.0.0.1:8080"}})
    fake = _FakeProc()
    sdcpp.attach_proc_for_tests(fake)
    gpu_lease.release_on_quit()
    assert fake.poll() is not None
    assert "stop-sdcli" in order
    assert "start-llama" in order
    assert order.index("stop-sdcli") < order.index("start-llama")


def test_image_backend_defaults_to_sdcpp_and_comfy_is_optional(tmp_path: Path) -> None:
    assert resolve_backend(None) == "sdcpp"
    assert resolve_backend("") == "sdcpp"
    assert resolve_backend("ComfyUI") == "comfy"
    shipped = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "arelis" / "config" / "default.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert resolve_backend(str(shipped["tools"]["image"]["backend"])) == "sdcpp"
    tool = ImageTool(comfy_url="http://127.0.0.1:9", output_dir=str(tmp_path))
    assert tool.backend == "sdcpp"
    comfy = ImageTool(
        comfy_url="http://127.0.0.1:9", output_dir=str(tmp_path), backend="comfy"
    )
    assert comfy.backend == "comfy"


def test_sdcpp_download_cleans_up_partial_files_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("arelis.tools.sdcpp.install_root", lambda config=None: tmp_path)
    monkeypatch.setattr(
        "arelis.tools.sdcpp.bin_dir", lambda config=None: tmp_path / "bin"
    )
    monkeypatch.setattr(
        "arelis.tools.sdcpp.file_is_ready",
        lambda spec, config=None: spec.key != "model",
    )

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self, size: int):
            del size
            yield b"partial" * 1024
            raise httpx.ReadError("cut off")

    class _Down:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def stream(self, *args: object, **kwargs: object):
            return _Stream()

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: _Down())
    from arelis.tools.sdcpp import ensure_files

    with pytest.raises(ModelError):
        ensure_files({"tools": {"image": {"backend": "sdcpp"}}})
    leftovers = [path for path in tmp_path.rglob("*") if path.suffix in {".part", ".gguf"}]
    assert leftovers == []


def test_sdcpp_command_uses_config_flags() -> None:
    cmd = command_from_config(
        {
            "tools": {
                "image": {
                    "sdcpp": {
                        "width": 768,
                        "height": 512,
                        "steps": 8,
                        "cfg": 1.5,
                        "sampler": "euler",
                        "offload_to_cpu": False,
                        "diffusion_fa": True,
                        "vae_tiling": True,
                    }
                }
            }
        },
        binary="sd-cli.exe",
        model="flux-2-klein-4b-Q4_0.gguf",
        llm="Qwen3-4B-Q4_K_M.gguf",
        vae="flux2-vae.safetensors",
        prompt_file="prompt.txt",
        output="out.png",
        seed=42,
    )
    assert cmd[0] == "sd-cli.exe"
    assert cmd[cmd.index("--diffusion-model") + 1] == "flux-2-klein-4b-Q4_0.gguf"
    assert cmd[cmd.index("--llm") + 1] == "Qwen3-4B-Q4_K_M.gguf"
    assert cmd[cmd.index("--vae") + 1] == "flux2-vae.safetensors"
    assert cmd[cmd.index("--prompt-file") + 1] == "prompt.txt"
    assert cmd[cmd.index("-W") + 1] == "768"
    assert cmd[cmd.index("-H") + 1] == "512"
    assert cmd[cmd.index("--steps") + 1] == "8"
    assert cmd[cmd.index("--cfg-scale") + 1] == "1.5"
    assert cmd[cmd.index("--sampling-method") + 1] == "euler"
    assert cmd[cmd.index("--seed") + 1] == "42"
    assert "--offload-to-cpu" not in cmd
    assert "--diffusion-fa" in cmd
    assert "--vae-tiling" in cmd
    assert cmd[cmd.index("-o") + 1] == "out.png"
    default = command_from_config(
        {},
        binary="sd-cli.exe",
        model="m.gguf",
        llm="l.gguf",
        vae="v.safetensors",
        prompt_file="p.txt",
        output="o.png",
        seed=7,
    )
    assert default[default.index("-W") + 1] == "1024"
    assert default[default.index("-H") + 1] == "1024"
    assert default[default.index("--steps") + 1] == "4"
    assert default[default.index("--cfg-scale") + 1] == "1.0"
    assert "--offload-to-cpu" in default
    assert "--diffusion-fa" in default
    assert "--vae-tiling" in default


def test_image_edit_is_not_yet_unless_comfy_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = _png(project / "source.png")
    roots = WorkspaceRoots([RootEntry(name="project", path=project.resolve())])
    monkeypatch.setattr("arelis.tools.image.discover_comfy", lambda: None)
    monkeypatch.setattr(
        "arelis.tools.image.comfy_is_healthy", lambda *args, **kwargs: False
    )
    tool = ImageTool(
        comfy_url="http://127.0.0.1:9",
        output_dir=str(tmp_path / "out"),
        backend="sdcpp",
        workspace=roots,
        launch_cwd="",
    )
    result = asyncio.run(tool.run(prompt="make this a watercolor", path=str(source)))
    assert result.ok is False
    assert NOT_YET in result.output


def test_picture_lease_posts_pause_wording_to_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.core.events import EventType
    from arelis.tools.gpu_lease import CHAT_PAUSED, CHAT_RESUMING
    from arelis.tools.image import schedule_image_progress

    posted: list[object] = []

    class _Bus:
        async def publish(self, event: object) -> None:
            posted.append(event)

    _install_lease_spies()
    _patch_sdcpp_ready(monkeypatch, tmp_path)
    config = {
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
        "tools": {"image": {"backend": "sdcpp", "sdcpp": {"idle_timeout_s": 90}}},
    }
    tool = ImageTool(
        comfy_url="http://127.0.0.1:9",
        output_dir=str(tmp_path / "out"),
        backend="sdcpp",
        config=config,
    )
    bus = _Bus()
    tool.set_progress(lambda line: schedule_image_progress(bus, line))

    async def _run() -> object:
        result = await tool.run(prompt="a red fox")
        # Let the REPLY_NOTE tasks scheduled in the lease finally block run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return result

    result = asyncio.run(_run())
    assert result.ok is True
    notes = [
        event
        for event in posted
        if getattr(event, "type", None) == EventType.REPLY_NOTE
    ]
    messages = [str(event.payload.get("message") or "") for event in notes]
    assert CHAT_PAUSED in messages
    assert CHAT_RESUMING in messages
    assert all(not getattr(event, "payload", {}).get("image_progress") for event in notes)

def test_restore_does_not_block_the_event_loop_and_posts_resuming_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore must run off the asyncio thread so the resume line can post."""
    import time

    from arelis.tools.gpu_lease import CHAT_RESUMING
    from arelis.tools.image import schedule_image_progress

    order: list[str] = []

    def stop(url: str) -> bool:
        del url
        return True

    def ensure(url: str, args: list[str] | None) -> None:
        del url, args
        order.append("ensure_start")
        time.sleep(0.4)
        order.append("ensure_end")

    gpu_lease.reset_for_tests(
        stop=stop,
        ensure=ensure,
        nowait=lambda url, args: None,
        args=lambda _config: ["llama-server"],
    )
    _patch_sdcpp_ready(monkeypatch, tmp_path)
    config = {
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
        "tools": {"image": {"backend": "sdcpp", "sdcpp": {"idle_timeout_s": 90}}},
    }
    tool = ImageTool(
        comfy_url="http://127.0.0.1:9",
        output_dir=str(tmp_path / "out"),
        backend="sdcpp",
        config=config,
    )

    class _Bus:
        async def publish(self, event: object) -> None:
            message = str(getattr(event, "payload", {}).get("message") or "")
            if message == CHAT_RESUMING:
                order.append("resuming")

    bus = _Bus()
    tool.set_progress(lambda line: schedule_image_progress(bus, line))

    async def _run() -> object:
        async def ticker() -> None:
            while True:
                order.append("tick")
                await asyncio.sleep(0.05)

        tick_task = asyncio.create_task(ticker())
        try:
            return await tool.run(prompt="a red fox")
        finally:
            tick_task.cancel()
            try:
                await tick_task
            except asyncio.CancelledError:
                pass

    result = asyncio.run(_run())
    assert result.ok is True
    assert "ensure_start" in order
    assert "ensure_end" in order
    start = order.index("ensure_start")
    end = order.index("ensure_end")
    mid = order[start + 1 : end]
    assert "tick" in mid
    assert "resuming" in mid

