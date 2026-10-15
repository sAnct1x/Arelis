"""load_tools in tail mode, and argument types on every tool call.

Off stays the shipped tools list, byte for byte, and load_tools is not
registered. tail returns a group's schemas as the tool result and leaves
the frozen tools array alone. A later call to one of those tools still
runs, even though its name is not in that array. String arguments are
converted from the tool's own schema. Values that already have the right
type are left alone. Front does not grow the array in this change.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

_GOLDEN = Path(__file__).parent / "fixtures" / "worst_profile_tools.json"


def _names(specs: list[dict[str, Any]]) -> list[str]:
    return [spec["function"]["name"] for spec in specs]


def _registry(mode: str) -> Any:
    """Worst-profile registry with agent.tool_loading set to mode.

    The copy keeps this from writing the flag into the cached config.
    """
    import arelis.tools as tools_mod
    from arelis.config import load_config
    from arelis.tools import build_tool_registry
    from scripts.measure_tool_schema import _EXAMPLE_MAIL, _EXAMPLE_SMS, _router

    config = dict(load_config())
    agent = dict(config.get("agent") or {})
    agent["tool_loading"] = mode
    config["agent"] = agent
    config["_vl_model_installed"] = True
    config["_session_platform"] = "win32"
    saved_mail = tools_mod.load_account
    saved_sms = tools_mod.load_sms_account
    try:
        tools_mod.load_account = lambda path=None: _EXAMPLE_MAIL
        tools_mod.load_sms_account = lambda path=None: _EXAMPLE_SMS
        return build_tool_registry(
            config, allow_send=True, attended=True, router=_router()
        )
    finally:
        tools_mod.load_account = saved_mail
        tools_mod.load_sms_account = saved_sms


def _stub(tool: Any) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    async def run(**kwargs: Any) -> Any:
        from arelis.tools.base import ToolResult

        seen.append(kwargs)
        return ToolResult(ok=True, output="ok")

    tool.run = run
    return seen


def test_flag_off_byte_identical_and_load_tools_absent() -> None:
    from arelis.core.tool_surface import session_tool_schemas
    from scripts.measure_tool_schema import registry_for_profile, tool_specs

    golden = _GOLDEN.read_text(encoding="utf-8")
    reg = registry_for_profile("worst")
    assert "load_tools" not in reg.names()
    sent = session_tool_schemas(reg, {"tool_loading": "off"})
    absent = session_tool_schemas(registry_for_profile("worst"), {})
    assert json.dumps(sent, indent=2) + "\n" == golden
    assert json.dumps(absent, indent=2) + "\n" == golden
    assert json.dumps(tool_specs(reg), indent=2) + "\n" == golden
    assert "load_tools" not in _names(sent)
    assert "load_tools" not in _names(absent)


def test_number_text_strips_sign_and_leading_zeros() -> None:
    """Number params take padded numeric text. None of these fields is an id."""
    from scripts.measure_tool_schema import registry_for_profile

    reg = registry_for_profile("worst")
    fetch = _stub(reg.get("web_fetch"))
    image = _stub(reg.get("image"))
    for raw, expected in ((" 5 ", 5), ("+1", 1), ("007", 7)):
        result = asyncio.run(reg.call("web_fetch", url="https://example.com/x", max_chars=raw))
        assert result.ok is True
        assert fetch[-1]["max_chars"] == expected
        assert type(fetch[-1]["max_chars"]) is int
    cfg = asyncio.run(reg.call("image", prompt="x", cfg="007"))
    assert cfg.ok is True
    assert image[-1]["cfg"] == 7
    assert type(image[-1]["cfg"]) is int


def test_confirm_card_shows_the_converted_args() -> None:
    """The Allow card and the tool run see the same converted values."""
    from unittest.mock import AsyncMock

    from arelis.core.turn_confirm import RUN, confirm_call
    from arelis.core.turn_context import TurnContext
    from scripts.measure_tool_schema import registry_for_profile

    reg = registry_for_profile("worst")
    seen = _stub(reg.get("image"))
    width = "512"
    flag = "false"
    args = {"prompt": "a cat", "width": width, "remove_background": flag}

    class _Bus:
        async def publish(self, event: Any) -> None:
            return None

    class _Loop:
        def __init__(self) -> None:
            self.bus = _Bus()
            self.tools = reg
            self.memory = None
            self._trace: list[str] = []
            self._expected_tools: set[str] = set()
            self._look = None
            self._timer = None
            self.confirm_writes = True
            self.confirm_image = True
            self.confirm_send = True
            self.confirm_browser = True
            self.confirm_desktop = True
            self.confirm_vision = True
            self.confirm_run = True
            self.ask_is_grant = True
            self.tools_used: set[str] = set()
            self._private_url_note = ""
            self.request_confirm = AsyncMock(return_value="allow")

        def _tool_message(self, name: str, content: str) -> dict[str, Any]:
            return {"role": "tool", "name": name, "content": content}

        async def _confirm_wait_heartbeat(self, name: str, started: float) -> None:
            await asyncio.sleep(3600)

    loop = _Loop()

    async def _run() -> None:
        action, _summary, _fp = await confirm_call(
            loop,
            TurnContext(text="draw a cat", role="fast"),
            "image",
            args,
            text="draw a cat",
            fail_counts={},
            skip_counts={},
            messages=[],
            drop_wander=lambda _name: None,
        )
        assert action == RUN
        card = loop.request_confirm.await_args
        assert card is not None
        card_args = card.args[2]
        assert card_args is args
        assert type(card_args["width"]) is int
        assert card_args["width"] == 512
        assert card_args["remove_background"] is False
        result = await reg.call("image", **args)
        assert result.ok is True
        assert seen[-1]["width"] is card_args["width"]
        assert seen[-1]["remove_background"] is False

    asyncio.run(_run())
