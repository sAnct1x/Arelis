"""Session tool set and schema budget.

The list the model sees is chosen once for the session: desktop only on
Windows, vision and camera only when the VL model is installed, mail and
SMS only when those accounts exist. The startup warmup and the first turn
must send the same bytes. Enabling a feature in Settings rebuilds that
list once.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from arelis.tools import build_tool_registry


def _router() -> SimpleNamespace:
    return SimpleNamespace(provider=SimpleNamespace(list_models=None))


def _bare_config(**extra: object) -> dict:
    config: dict = {"tools": {}, "agent": {}, "ollama": {}, "models": {}}
    config.update(extra)
    return config


def test_desktop_registers_only_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _bare_config()
    monkeypatch.setattr(sys, "platform", "darwin")
    mac = build_tool_registry(config, allow_send=True, attended=True)
    assert "desktop" not in mac.names()

    monkeypatch.setattr(sys, "platform", "linux")
    linux = build_tool_registry(config, allow_send=True, attended=True)
    assert "desktop" not in linux.names()

    monkeypatch.setattr(sys, "platform", "win32")
    windows = build_tool_registry(config, allow_send=True, attended=True)
    assert "desktop" in windows.names()
    jobs = build_tool_registry(config, allow_send=False, attended=False)
    assert "desktop" not in jobs.names()


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


def test_session_schema_list_is_frozen() -> None:
    from arelis.config import load_config
    from arelis.core.tool_surface import session_tool_schemas

    config = load_config()
    config["_vl_model_installed"] = False
    registry = build_tool_registry(
        config, allow_send=True, attended=True, router=_router()
    )
    agent = config.get("agent")
    first = session_tool_schemas(registry, agent)
    second = session_tool_schemas(registry, agent)
    assert first is second
    assert json.dumps(first) == json.dumps(second)


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


def test_missing_sms_hint_stays_for_the_fallback_reply() -> None:
    from arelis.core.tool_surface import apply_expected

    loop = SimpleNamespace(
        _expected_tools={"send_sms", "inbox"},
        _look=None,
        memory=SimpleNamespace(messages=[]),
    )
    apply_expected(
        loop,
        set(),
        text="text my wife that I am running late",
        available_all=set(),
    )
    assert "send_sms" in loop._expected_tools
    assert "inbox" in loop._expected_tools


def test_ci_and_worst_caps_are_one_table() -> None:
    from scripts.measure_tool_schema import (
        CAP_RAISE_COLD_SECONDS,
        CAP_RAISE_TOKENS,
        COLD_SECONDS_PER_100_TOKENS,
        SCHEMA_TOKEN_CAP,
        schema_token_estimate,
    )

    assert schema_token_estimate(23_570) == 7_132
    assert SCHEMA_TOKEN_CAP["default"] == 7_036
    assert SCHEMA_TOKEN_CAP["worst"] == 7_640
    assert SCHEMA_TOKEN_CAP["default"] == schema_token_estimate(5_400 * 4) + CAP_RAISE_TOKENS
    assert CAP_RAISE_COLD_SECONDS == 1.7
    assert abs(CAP_RAISE_TOKENS * COLD_SECONDS_PER_100_TOKENS / 100 - 1.65) < 0.001
    from tests.test_tool_schema_quality import MAX_SCHEMA_TOKENS

    assert MAX_SCHEMA_TOKENS == SCHEMA_TOKEN_CAP["default"]


def test_profiles_match_warmup_and_a_second_build() -> None:
    from arelis.config import load_config
    from arelis.core.tool_surface import session_tool_schemas
    from arelis.llm.startup import prefix_warmup_for
    from scripts.measure_tool_schema import registry_for_profile

    config = load_config()
    agent = config.get("agent")
    for profile in ("default", "worst", "mac"):
        first = registry_for_profile(profile)
        second = registry_for_profile(profile)
        turn = session_tool_schemas(first, agent)
        again = session_tool_schemas(first, agent)
        other = session_tool_schemas(second, agent)
        warm = prefix_warmup_for(config, first)
        assert warm is not None, profile
        blob = json.dumps(turn)
        assert blob == json.dumps(again) == json.dumps(other) == json.dumps(warm.tools), profile
        assert again is turn


def test_default_and_worst_case_budgets() -> None:
    from scripts.measure_tool_schema import (
        SCHEMA_TOKEN_CAP,
        measure,
        registry_for_profile,
        tool_specs,
    )

    default = measure(tool_specs())
    worst = measure(tool_specs(registry_for_profile("worst")))
    mac = measure(tool_specs(registry_for_profile("mac")))
    assert default["schema_tokens_approx"] <= SCHEMA_TOKEN_CAP["default"]
    assert worst["tools"] == 51
    assert worst["schema_tokens_approx"] <= SCHEMA_TOKEN_CAP["worst"]
    assert worst["schema_tokens_approx"] > default["schema_tokens_approx"]
    assert mac["schema_tokens_approx"] <= SCHEMA_TOKEN_CAP["default"]
    assert mac["tools"] < worst["tools"]
    mac_names = {
        spec["function"]["name"] for spec in tool_specs(registry_for_profile("mac"))
    }
    assert "desktop" not in mac_names
    assert "vision" in mac_names
    assert "camera" in mac_names


def test_enabling_mail_rebuilds_once_and_reseeds(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from arelis.config import load_config
    from arelis.core.tool_surface import refresh_session_tools, session_tool_schemas
    from arelis.mail import MailAccount

    config = load_config()
    config["_vl_model_installed"] = False
    account = MailAccount(address="person@example.com", password="app-password")
    state = {"on": False}

    def _load(path: object = None) -> MailAccount | None:
        del path
        return account if state["on"] else None

    def _save(**kwargs: object) -> MailAccount:
        del kwargs
        state["on"] = True
        return account

    monkeypatch.setattr("arelis.tools.load_account", _load)
    monkeypatch.setattr("arelis.mail.save_account", _save)
    tools = build_tool_registry(
        config, allow_send=True, attended=True, router=_router()
    )
    assert "inbox" not in tools.names()
    assert "send_email" not in tools.names()
    # Settings just wrote the account. The next registry build can see it.
    state["on"] = True

    scheduled: list[object] = []

    def _schedule(coro: object, loop: object) -> SimpleNamespace:
        del loop
        scheduled.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _schedule)
    router = _router()
    orchestrator = SimpleNamespace(
        tools=tools,
        config=config,
        router=router,
        workspace=config.get("_workspace"),
        memory=SimpleNamespace(sink=None),
    )
    window = SimpleNamespace(
        orchestrator=orchestrator,
        config=config,
        router=router,
        loop=object(),
        bus=SimpleNamespace(),
    )
    assert refresh_session_tools(window) is True
    assert "inbox" in orchestrator.tools.names()
    assert "send_email" in orchestrator.tools.names()
    assert "schedule" in orchestrator.tools.names()
    assert len(scheduled) == 1
    frozen = session_tool_schemas(orchestrator.tools, config.get("agent"))
    assert session_tool_schemas(orchestrator.tools, config.get("agent")) is frozen
    assert "inbox" in {spec["function"]["name"] for spec in frozen}
    assert refresh_session_tools(window) is False
    assert len(scheduled) == 1


def test_tail_session_budget_is_the_core_list() -> None:
    """tail sends core plus load_tools, not the full worst-profile list."""
    from arelis.core.tool_surface import session_tool_schemas
    from arelis.tools.groups import CORE
    from scripts.measure_tool_schema import (
        registry_for_profile,
        schema_token_estimate,
        tool_specs,
    )

    reg = registry_for_profile("worst")
    registered = [spec["function"]["name"] for spec in tool_specs(reg)]
    core = [name for name in registered if name in set(CORE)]
    specs = session_tool_schemas(reg, {"tool_loading": "tail"})
    names = [spec["function"]["name"] for spec in specs]
    assert names == [*core, "load_tools"]
    tokens = schema_token_estimate(len(json.dumps(specs)))
    assert tokens <= 2000, tokens
