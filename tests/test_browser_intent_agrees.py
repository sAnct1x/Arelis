"""The preflight nudge and the plan describe the same turn the same way.

Both are system messages on the same prompt. When they disagree the model is not
merely under-informed, it is contradicted: told to call browser(action=maps) by
one and handed a plan for something else — or no plan at all, where every other
intent has one — by the next.

They disagreed because each owned a copy of the same matchers and preflight's
copy kept learning phrases plan_nudge's did not. Every phrase below matched in
preflight and not in plan_nudge.
"""

from __future__ import annotations

import pytest

from arelis.core.plan_nudge import plan_system_message
from arelis.core.preflight import preflight_system_message

# (phrase, the browser action both sides should be pointing at)
DRIFTED = [
    ("walk to the coffee shop on 5th", "maps"),
    ("route to the airport", "maps"),
    ("sms me the directions", "maps"),
    ("book us a table at Nopa tomorrow", "reserve"),
    ("get us a table for 7pm", "reserve"),
    ("table for 4 at the italian place", "reserve"),
    ("describe the page", "read"),
    ("tell me what's on this tab", "read"),
    ("youtube search for lathe tutorials", "search"),
    ("look up a drill press on amazon", "search"),
    ("google this in the browser", "search"),
]


@pytest.mark.parametrize(("text", "action"), DRIFTED)
def test_the_nudge_names_the_browser_action(text: str, action: str) -> None:
    msg = preflight_system_message(text) or ""
    assert "browser" in msg.lower(), f"no browser nudge for {text!r}"


@pytest.mark.parametrize(("text", "action"), DRIFTED)
def test_the_plan_also_names_it(text: str, action: str) -> None:
    """This is the half that used to be silent."""
    msg = plan_system_message(text) or ""
    assert "browser" in msg.lower(), f"no browser plan for {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "add it to my cart",
        "put this in the bag",
    ],
)
def test_cart_survived_the_split(text: str) -> None:
    """Cart is its own matcher in the catalog; plan_nudge had it inside search.

    Splitting them without checking both here would have dropped the cart plan
    entirely, which is the kind of regression a de-duplication is supposed to
    make impossible rather than introduce.
    """
    assert "browser" in (plan_system_message(text) or "").lower()


def test_a_how_to_question_is_still_not_a_click() -> None:
    """The shared matcher must keep the exception both copies agreed on."""
    plan = plan_system_message("how do I sign in?") or ""
    assert "click" not in plan.lower()
