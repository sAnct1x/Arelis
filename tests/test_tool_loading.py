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


def test_unknown_group_lists_valid_names() -> None:
    from arelis.tools.groups import GROUPS

    reg = _registry("tail")
    result = asyncio.run(reg.call("load_tools", groups=["nope", "images"]))
    assert result.ok is False
    assert "nope" in result.output
    for name in GROUPS:
        assert name in result.output
    assert reg.loaded_groups == []

    empty = asyncio.run(reg.call("load_tools", groups=[]))
    assert empty.ok is False
    assert "images" in empty.output
    assert reg.loaded_groups == []


def test_load_is_idempotent_and_tools_array_stays_frozen() -> None:
    from arelis.core.tool_surface import session_tool_schemas
    from arelis.tools.groups import GROUPS

    reg = _registry("tail")
    agent = {"tool_loading": "tail"}
    frozen = session_tool_schemas(reg, agent)
    before = _names(frozen)
    assert "image" not in before
    assert before[-1] == "load_tools"

    first = asyncio.run(reg.call("load_tools", groups=["images", "images", "astro"]))
    assert first.ok is True
    assert reg.loaded_groups == ["images", "astro"]
    again = asyncio.run(reg.call("load_tools", groups='["images"]'))
    assert again.ok is True
    assert reg.loaded_groups == ["images", "astro"]

    lines = [line for line in first.output.splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]
    got = _names(parsed)
    want = [name for name in (*GROUPS["images"], *GROUPS["astro"]) if name in reg.names()]
    assert got == want
    image_lines = [line for line in again.output.splitlines() if line.strip()]
    assert _names([json.loads(line) for line in image_lines]) == [
        name for name in GROUPS["images"] if name in reg.names()
    ]

    after = session_tool_schemas(reg, agent)
    assert after is frozen
    assert _names(after) == before
    assert "image" not in _names(after)


def test_tail_loaded_call_string_args_coerced() -> None:
    """Loaded image tools are absent from the tools array and still run.

    "512" becomes 512. A JSON object string becomes an object, including
    integer fields inside it. A JSON array string becomes a list.
    """
    from arelis.core.tool_surface import session_tool_schemas

    reg = _registry("tail")
    agent = {"tool_loading": "tail"}
    frozen = session_tool_schemas(reg, agent)
    assert "image" not in _names(frozen)
    assert "image_edit" not in _names(frozen)

    loaded = asyncio.run(reg.call("load_tools", groups=["images"]))
    assert loaded.ok is True
    assert '"name": "image"' in loaded.output
    assert reg.loaded_groups == ["images"]
    assert session_tool_schemas(reg, agent) is frozen

    image = _stub(reg.get("image"))
    prompt = "a red fox"
    box = asyncio.run(
        reg.call(
            "image",
            prompt=prompt,
            width="512",
            height="512",
            remove_background="false",
            mask_box="[1, 2, 3, 4]",
        )
    )
    assert box.ok is True
    got = image[-1]
    assert got["prompt"] is prompt
    assert got["width"] == 512 and type(got["width"]) is int
    assert got["height"] == 512 and type(got["height"]) is int
    assert got["remove_background"] is False
    assert got["mask_box"] == [1, 2, 3, 4]

    edit = _stub(reg.get("image_edit"))
    path = "pic.png"
    edited = asyncio.run(
        reg.call(
            "image_edit",
            path=path,
            upscale="2",
            blur="1.5",
            grayscale="true",
            scale_bar='{"length": "40", "label": "1 km"}',
        )
    )
    assert edited.ok is True
    args = edit[-1]
    assert args["path"] is path
    assert args["upscale"] == 2 and type(args["upscale"]) is int
    assert args["blur"] == 1.5 and type(args["blur"]) is float
    assert args["grayscale"] is True
    assert args["scale_bar"] == {"length": 40, "label": "1 km"}
    assert type(args["scale_bar"]["length"]) is int
    assert session_tool_schemas(reg, agent) is frozen


def test_typed_args_are_not_rewritten() -> None:
    """Conversion runs on every call and does not rebuild typed values."""
    from scripts.measure_tool_schema import registry_for_profile

    reg = registry_for_profile("worst")
    assert "load_tools" not in reg.names()
    edit = _stub(reg.get("image_edit"))
    path = "pic.png"
    scale = {"length": 40, "label": "1 km"}
    marks = [{"kind": "label", "x": 3, "y": 4, "text": "a"}]
    blur = 1.5
    result = asyncio.run(
        reg.call(
            "image_edit",
            path=path,
            upscale=2,
            blur=blur,
            grayscale=False,
            scale_bar=scale,
            annotate=marks,
        )
    )
    assert result.ok is True
    args = edit[-1]
    assert args["path"] is path
    assert args["upscale"] == 2 and type(args["upscale"]) is int
    assert args["blur"] is blur
    assert args["grayscale"] is False
    assert args["scale_bar"] is scale
    assert args["annotate"] is marks
    assert args["annotate"][0] is marks[0]


def test_coercion_applies_with_the_flag_off() -> None:
    """A core tool is in the tools array. String integers still convert."""
    from scripts.measure_tool_schema import registry_for_profile

    reg = registry_for_profile("worst")
    weather = _stub(reg.get("weather"))
    place = "2"
    result = asyncio.run(reg.call("weather", days="2", place=place))
    assert result.ok is True
    args = weather[-1]
    assert args["days"] == 2 and type(args["days"]) is int
    assert args["place"] is place


def test_failed_conversion_leaves_the_value() -> None:
    from scripts.measure_tool_schema import registry_for_profile

    reg = registry_for_profile("worst")
    image = _stub(reg.get("image"))
    bad_width = "nope"
    bad_box = "[1, 2"
    result = asyncio.run(
        reg.call("image", prompt="x", width=bad_width, mask_box=bad_box)
    )
    assert result.ok is True
    args = image[-1]
    assert args["width"] is bad_width
    assert args["mask_box"] is bad_box

    edit = _stub(reg.get("image_edit"))
    bad_upscale = "3"
    edited = asyncio.run(reg.call("image_edit", path="pic.png", upscale=bad_upscale))
    assert edited.ok is True
    assert edit[-1]["upscale"] is bad_upscale


def test_loaded_groups_stick_on_the_session_registry() -> None:
    """A new turn builds a new loop. The loaded set stays on the registry."""
    from arelis.core.agent_loop import AgentLoop
    from arelis.core.bus import EventBus
    from arelis.core.memory import SessionMemory

    reg = _registry("tail")
    loaded = asyncio.run(reg.call("load_tools", groups=["code"]))
    assert loaded.ok is True

    def _loop() -> Any:
        return AgentLoop(
            EventBus(),
            object(),
            reg,
            SessionMemory(),
            "persona",
            {"agent": {"tool_loading": "tail"}},
            request_confirm=lambda *_a, **_k: None,
            is_cancelled=lambda: False,
        )

    first = _loop()
    second = _loop()
    assert first.loaded_groups is reg.loaded_groups
    assert second.loaded_groups is first.loaded_groups
    assert list(first.loaded_groups) == ["code"]


def test_front_does_not_grow_the_tools_array() -> None:
    """Front keeps the frozen core list. Schemas come back on the result."""
    from arelis.core.tool_surface import session_tool_schemas

    reg = _registry("front")
    agent = {"tool_loading": "front"}
    frozen = session_tool_schemas(reg, agent)
    before = _names(frozen)
    assert before[-1] == "load_tools"
    assert "image" not in before

    result = asyncio.run(reg.call("load_tools", groups=["images"]))
    assert result.ok is True
    assert '"name": "image"' in result.output
    assert reg.loaded_groups == ["images"]
    assert session_tool_schemas(reg, agent) is frozen
    assert _names(session_tool_schemas(reg, agent)) == before
