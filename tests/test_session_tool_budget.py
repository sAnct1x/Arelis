"""Session tool set and schema budget.

The list the model sees is chosen once for the session: desktop only on
Windows, vision and camera only when the launch line has an mmproj file,
mail and SMS only when those accounts exist. The startup warmup and the
first turn must send the same bytes. Enabling a feature in Settings
rebuilds that list once.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from arelis.tools import build_tool_registry


def _router() -> SimpleNamespace:
    return SimpleNamespace(provider=SimpleNamespace(list_models=None))


def _bare_config(**extra: object) -> dict:
    config: dict = {"tools": {}, "agent": {}, "models": {}}
    config.update(extra)
    return config


def test_vision_registers_only_when_the_launch_line_has_an_mmproj(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The vision tool follows the picture file named by the launch args.

    Args that point at a missing mmproj do not register it. Writing that
    file does. A model list is not consulted. A profile that does not set
    a model path resolves the default 35B file the same way launch_args_for
    does, and vision still stays off until that mmproj file exists.
    """
    from arelis.llm.llama_launch import (
        MMPROJ_FILENAME,
        MODEL_FILENAME,
        launch_args_for,
    )

    model = tmp_path / "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
    model.write_bytes(b"gguf")
    config = {
        "tools": {},
        "agent": {},
        "models": {},
        "llamacpp": {
            "model": str(model),
            "binary": "llama-server",
            "base_url": "http://127.0.0.1:8080",
        },
    }
    args = launch_args_for(config)
    assert args is not None
    mmproj = Path(args[args.index("--mmproj") + 1])
    assert not mmproj.is_file()

    router = _router()
    absent = build_tool_registry(
        config, allow_send=True, attended=True, router=router
    )
    assert "vision" not in absent.names()

    mmproj.write_bytes(b"mmproj")
    present = build_tool_registry(
        config, allow_send=True, attended=True, router=router
    )
    assert "vision" in present.names()

    weights = tmp_path / "weights"
    weights.mkdir()
    monkeypatch.setattr("arelis.paths.models_dir", lambda: weights)
    monkeypatch.setattr("arelis.llm.llama_launch._cache_roots", lambda: [])
    monkeypatch.setattr("arelis.paths.published_data_dir", lambda: None)

    import httpx

    def _server_down(url: str, timeout: float = 0.4, follow_redirects: bool = False) -> None:
        del url, timeout, follow_redirects
        raise httpx.ConnectError("down")

    monkeypatch.setattr("arelis.llm.llama_launch.httpx.get", _server_down)
    bare = {
        "tools": {},
        "agent": {},
        "models": {},
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
    }
    assert launch_args_for(bare) is None
    nowhere = build_tool_registry(
        bare, allow_send=True, attended=True, router=router
    )
    assert "vision" not in nowhere.names()

    default_gguf = weights / MODEL_FILENAME
    default_gguf.write_bytes(b"gguf")
    default_args = launch_args_for(bare)
    assert default_args is not None
    default_mmproj = Path(default_args[default_args.index("--mmproj") + 1])
    assert default_mmproj == (weights / MMPROJ_FILENAME).resolve()
    assert not default_mmproj.is_file()
    named = {
        "tools": {},
        "agent": {},
        "models": {},
        "llamacpp": {
            "model": MODEL_FILENAME,
            "base_url": "http://127.0.0.1:8080",
        },
    }
    assert launch_args_for(named) == default_args
    missing_picture = build_tool_registry(
        bare, allow_send=True, attended=True, router=router
    )
    assert "vision" not in missing_picture.names()
    assert "camera" not in missing_picture.names()

    default_mmproj.write_bytes(b"mmproj")
    with_picture = build_tool_registry(
        bare, allow_send=True, attended=True, router=router
    )
    assert "vision" in with_picture.names()
    assert "camera" in with_picture.names()
    by_name = build_tool_registry(
        named, allow_send=True, attended=True, router=router
    )
    assert "vision" in by_name.names()

    # Fresh profile: this data dir has no weights. The installed profile does.
    # build_router is the startup path (migrate, then the launch line the
    # provider keeps). The registry is built from that same config.
    from arelis.llm import build_router

    empty = tmp_path / "empty-weights"
    empty.mkdir()
    published = tmp_path / "published"
    (published / "models").mkdir(parents=True)
    (published / "models" / MODEL_FILENAME).write_bytes(b"gguf")
    monkeypatch.setattr("arelis.paths.models_dir", lambda: empty)
    monkeypatch.setattr("arelis.paths.published_data_dir", lambda: published)
    monkeypatch.setattr("arelis.llm.llama_launch._cache_roots", lambda: [])

    def _server_down(url: str, timeout: float = 0.4, follow_redirects: bool = False) -> None:
        del url, timeout, follow_redirects
        raise httpx.ConnectError("down")

    monkeypatch.setattr("arelis.llm.llama_launch.httpx.get", _server_down)
    profile = {
        "llm": {"provider": "llamacpp"},
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
        "models": {},
        "router": {},
        "tools": {},
        "agent": {},
    }
    seat = build_router(profile)
    assert profile["llamacpp"]["model"] == MODEL_FILENAME
    assert seat.provider._launch_args
    fresh_missing = build_tool_registry(
        profile, allow_send=True, attended=True, router=seat
    )
    assert "vision" not in fresh_missing.names()
    (published / "models" / MMPROJ_FILENAME).write_bytes(b"mmproj")
    fresh = build_tool_registry(
        profile, allow_send=True, attended=True, router=seat
    )
    assert "vision" in fresh.names()

    # Relative path from the data dir, not from the process working directory.
    rel_root = tmp_path / "rel"
    (rel_root / "models").mkdir(parents=True)
    (rel_root / "models" / MODEL_FILENAME).write_bytes(b"gguf")
    (rel_root / "models" / MMPROJ_FILENAME).write_bytes(b"mmproj")
    monkeypatch.setattr("arelis.paths.user_data_dir", lambda: rel_root)
    monkeypatch.setattr("arelis.paths.models_dir", lambda: empty)
    monkeypatch.setattr("arelis.paths.published_data_dir", lambda: None)
    relative = {
        "tools": {},
        "agent": {},
        "models": {},
        "llamacpp": {
            "model": f"models/{MODEL_FILENAME}",
            "base_url": "http://127.0.0.1:8080",
        },
    }
    relative_args = launch_args_for(relative)
    assert relative_args is not None
    assert Path(relative_args[relative_args.index("-m") + 1]) == (
        rel_root / "models" / MODEL_FILENAME
    ).resolve()
    by_relative = build_tool_registry(
        relative, allow_send=True, attended=True, router=router
    )
    assert "vision" in by_relative.names()

    # No file this profile can see. The server already up names its GGUF.
    # modalities.vision is not enough: the picture file has to be on disk.
    server_dir = tmp_path / "already-up"
    server_dir.mkdir()
    server_model = server_dir / MODEL_FILENAME
    server_model.write_bytes(b"gguf")
    monkeypatch.setattr("arelis.paths.models_dir", lambda: empty)
    monkeypatch.setattr("arelis.paths.published_data_dir", lambda: None)
    monkeypatch.setattr("arelis.paths.user_data_dir", lambda: empty)

    class _Props:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "model_path": str(server_model),
                "modalities": {"vision": True},
            }

    def _props(url: str, timeout: float = 0.4, follow_redirects: bool = False) -> _Props:
        del timeout, follow_redirects
        assert url == "http://127.0.0.1:8080/props"
        return _Props()

    monkeypatch.setattr("arelis.llm.llama_launch.httpx.get", _props)
    running = {
        "tools": {},
        "agent": {},
        "models": {},
        "llamacpp": {"base_url": "http://127.0.0.1:8080"},
    }
    assert launch_args_for(running) is None
    spoke = build_tool_registry(
        running, allow_send=True, attended=True, router=router
    )
    assert "vision" not in spoke.names()
    (server_dir / MMPROJ_FILENAME).write_bytes(b"mmproj")
    heard = build_tool_registry(
        running, allow_send=True, attended=True, router=router
    )
    assert "vision" in heard.names()
    assert "camera" in heard.names()


def test_vision_and_camera_need_the_vl_model() -> None:
    router = _router()
    missing = _bare_config(_vl_model_installed=False)
    off = build_tool_registry(missing, allow_send=True, attended=True, router=router)
    assert "vision" not in off.names()
    assert "camera" not in off.names()

    present = _bare_config(_vl_model_installed=True)
    on = build_tool_registry(present, allow_send=True, attended=True, router=router)
    assert "vision" in on.names()
    assert "camera" in on.names()

    no_router = build_tool_registry(present, allow_send=True, attended=True)
    assert "vision" not in no_router.names()
    assert "camera" not in no_router.names()


def test_absent_hint_tools_are_skipped() -> None:
    """Desktop on a Mac, or vision without the VL model, must not raise."""
    from arelis.core.tool_surface import apply_expected

    loop = SimpleNamespace(
        _expected_tools={"desktop", "vision", "camera", "weather"},
        _look=None,
        memory=SimpleNamespace(messages=[]),
    )
    available, visible = apply_expected(
        loop,
        {"weather", "calculator"},
        text="what is the weather today",
        available_all={"weather", "calculator"},
    )
    assert "desktop" not in available
    assert "vision" not in available
    assert "camera" not in available
    assert visible == available
    assert "desktop" not in loop._expected_tools
    assert "vision" not in loop._expected_tools
    assert "camera" not in loop._expected_tools
    assert "weather" in loop._expected_tools


