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

from arelis.tools import build_tool_registry


def _router() -> SimpleNamespace:
    return SimpleNamespace(provider=SimpleNamespace(list_models=None))


def _bare_config(**extra: object) -> dict:
    config: dict = {"tools": {}, "agent": {}, "models": {}}
    config.update(extra)
    return config


def test_vision_registers_only_when_the_launch_line_has_an_mmproj(
    tmp_path: Path,
) -> None:
    """The vision tool follows the picture file named by the launch args.

    Args that point at a missing mmproj do not register it. Writing that
    file does. A model list is not consulted.
    """
    from arelis.llm.llama_launch import launch_args_for

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


