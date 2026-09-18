"""The tool surface was built twice and the two copies had drifted.

`turn_prepare` builds it for round one, `turn_round` rebuilds it on escalate.
Same seven steps, same order, written out twice — except the escalate copy
never passed `extra_skill_ids`, so the active room's skills were in reach
before the turn escalated and gone after.

That drift is currently latent, not live: `filter_tool_names` ignores
`extra_skill_ids` unless `skill_tool_subset` or `research_tool_subset` is on,
and the shipped config has both off. `test_room_skills_are_load_bearing_when_subsetting_is_on`
below is the one that says why it still mattered — turn either flag on and the
escalate round starts answering with a narrower surface than round one, for no
reason anyone could see from either file.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arelis.core.tool_subset import filter_tool_names
from arelis.core.tool_surface import apply_expected, base_surface

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


def _room(*skills: str):
    return SimpleNamespace(spec=SimpleNamespace(skills=list(skills)))


def _cfg(**kw):
    base = {"research_tool_subset": False, "skill_tool_subset": False}
    base.update(kw)
    return base


# --- the drift itself --------------------------------------------------------


def test_room_skills_are_load_bearing_when_subsetting_is_on():
    """Without this, "the room's skills are dropped on escalate" is a claim
    about code that does nothing. With subsetting on, it is 64 of 192
    text/skill/flag combinations."""
    kw = dict(role="fast", text="hello", enabled=False, skill_subset=True, history=[])
    bare = filter_tool_names(ALL, **kw)
    with_room = filter_tool_names(ALL, **kw, extra_skill_ids=("web",))
    assert with_room - bare == {"scrape", "web_fetch", "web_search"}


def test_base_surface_passes_the_room_through():
    loop = _loop()
    cfg = _cfg(skill_tool_subset=True)
    bare, _ = base_surface(loop, set(ALL), role="fast", text="hello", agent_cfg=cfg)
    roomy, _ = base_surface(
        loop,
        set(ALL),
        role="fast",
        text="hello",
        agent_cfg=cfg,
        active_room=_room("web"),
    )
    assert roomy - bare == {"scrape", "web_fetch", "web_search"}


def test_no_room_is_not_an_error():
    loop = _loop()
    available, visible = base_surface(loop, set(ALL), role="fast", text="hello", agent_cfg=_cfg())
    assert available and available == visible


# --- the steps that were copied ----------------------------------------------


def test_a_look_turn_collapses_to_the_look_tools():
    loop = _loop(look=object())
    available, visible = base_surface(
        loop, set(ALL), role="fast", text="what is this", agent_cfg=_cfg()
    )
    assert available == visible
    assert "send_sms" not in available
    assert available < ALL


def test_a_look_turn_drops_both_sends():
    """A turn that is looking at a picture cannot also be texting someone."""
    loop = _loop(look=object())
    available, _ = apply_expected(loop, set(ALL), text="what is this", available_all=set(ALL))
    assert "send_sms" not in available
    assert "send_email" not in available


def test_an_expected_tool_is_offered_even_if_the_subset_dropped_it():
    loop = _loop(expected={"analyze"})
    available, _ = apply_expected(
        loop, {"web_search"}, text="what did we spend", available_all=set(ALL)
    )
    assert "analyze" in available


def test_available_and_visible_agree_after_apply_expected():
    """Both copies set `visible = available` after every narrowing step. If
    they ever diverge the model is offered a schema it is not allowed to use."""
    loop = _loop(expected={"weather"})
    available, visible = apply_expected(
        loop, set(ALL), text="weather tomorrow", available_all=set(ALL)
    )
    assert available == visible


def test_apply_expected_does_not_mutate_its_argument():
    """`turn_prepare` reads `available` again after this returns."""
    loop = _loop(look=object())
    original = set(ALL)
    handed_in = set(ALL)
    apply_expected(loop, handed_in, text="what is this", available_all=set(ALL))
    assert handed_in == original


# --- the two call sites must stay in step ------------------------------------


@pytest.mark.parametrize(
    "text",
    ["hello", "what did we spend in march", "text brian I am late", "weather tomorrow"],
)
@pytest.mark.parametrize("subset", [False, True])
def test_prepare_and_escalate_now_compute_the_same_surface(text, subset):
    """The whole point of the extraction. Same loop state, same room, same
    config — the answer cannot depend on which file asked."""
    cfg = _cfg(skill_tool_subset=subset)
    room = _room("web", "analyze")

    def surface():
        loop = _loop(expected={"analyze"})
        available, _ = base_surface(
            loop,
            set(ALL),
            role="fast",
            text=text,
            agent_cfg=cfg,
            active_room=room,
        )
        return apply_expected(loop, available, text=text, available_all=set(ALL))

    assert surface() == surface()
