"""Session tool set and schema budget.

The list the model sees is chosen once for the session: desktop only on
Windows, vision and camera only when the VL model is installed, mail and
SMS only when those accounts exist. The startup warmup and the first turn
must send the same bytes. Enabling a feature in Settings rebuilds that
list once.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arelis.tools import build_tool_registry


def _router() -> SimpleNamespace:
    return SimpleNamespace(provider=SimpleNamespace(list_models=None))


def _bare_config(**extra: object) -> dict:
    config: dict = {"tools": {}, "agent": {}, "ollama": {}, "models": {}}
    config.update(extra)
    return config


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


def test_vl_model_is_checked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.llm.startup import clear_vl_install_cache, vl_model_installed

    calls = {"n": 0}

    def _tags(base_url: str = "http://127.0.0.1:11434", *, timeout_s: float = 1.5) -> list[str]:
        del base_url, timeout_s
        calls["n"] += 1
        return ["qwen2.5vl:3b"]

    monkeypatch.setattr("arelis.llm.startup.list_installed_models", _tags)
    clear_vl_install_cache()
    config = {"models": {"vision": "qwen2.5vl:3b"}, "ollama": {}}
    assert vl_model_installed(config) is True
    assert vl_model_installed(config) is True
    assert calls["n"] == 1
    assert vl_model_installed(config, refresh=True) is True
    assert calls["n"] == 2

    calls["n"] = 0
    clear_vl_install_cache()

    def _down(base_url: str = "http://127.0.0.1:11434", *, timeout_s: float = 1.5) -> list[str]:
        del base_url, timeout_s
        calls["n"] += 1
        raise OSError("ollama down")

    monkeypatch.setattr("arelis.llm.startup.list_installed_models", _down)
    assert vl_model_installed(config) is False
    assert vl_model_installed(config) is False
    assert calls["n"] == 1

    forced = {"models": {"vision": "qwen2.5vl:3b"}, "_vl_model_installed": True}
    assert vl_model_installed(forced) is True
    assert calls["n"] == 1


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


