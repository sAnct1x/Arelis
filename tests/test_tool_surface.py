"""The tool surface was built twice and the two copies had drifted.

`turn_prepare` builds it for round one, `turn_round` rebuilds it on escalate.
Same seven steps, same order. Rooms used to own extra_skill_ids; that
product is gone. Look-turn collapse is what this file still pins.
"""

from __future__ import annotations

from types import SimpleNamespace

from arelis.core.tool_surface import base_surface

ALL = {
    "web_search",
    "scrape",
    "web_fetch",
    "analyze",
    "cas",
    "weather",
    "calculator",
    "document",
    "send_sms",
    "send_email",
    "contacts",
    "inbound_sms",
    "workspace",
    "image",
}


def _loop(*, look=None, expected=None, messages=None):
    return SimpleNamespace(
        _look=look,
        _expected_tools=set(expected or ()),
        _timer=None,
        memory=SimpleNamespace(messages=list(messages or ())),
    )


def _cfg(**kw):
    base = {"research_tool_subset": False, "skill_tool_subset": False}
    base.update(kw)
    return base


def test_a_look_turn_collapses_to_the_look_tools():
    loop = _loop(look=object())
    available, visible = base_surface(
        loop, set(ALL), role="fast", text="what is this", agent_cfg=_cfg()
    )
    assert available == visible
    assert "send_sms" not in available
    assert available < ALL
