"""A declined or complaining look must never start the webcam.

"no need to look at this" matched the camera pattern, classify_look returned
identify, and the camera plus vision tools became expected (and granted, so
no card). The look only counts when no "don't / no need / never / why did
you" sits before it in the same clause.
"""

from __future__ import annotations

import pytest

from arelis.core.image_refs import mentions_camera_look
from arelis.core.look import classify_look, has_look_context
from arelis.core.preflight import detect_intents

CAMERA_DECLINED = (
    "no need to look at this",
    "don't look at this, it's private",
    "why did you look at this?",
    "you shouldn't look at this",
    "no need to check the camera",
)


@pytest.mark.parametrize("text", CAMERA_DECLINED)
def test_declined_look_is_not_a_camera_look(text: str) -> None:
    assert classify_look(text) is None
    assert classify_look(text, dock_live=True) is None
    assert classify_look(text, fresh_path="outputs/images/camera_x.png") is None
    assert not has_look_context(text, dock_live=True)
    assert not mentions_camera_look(text, unnegated=True)


@pytest.mark.parametrize("text", CAMERA_DECLINED)
def test_declined_look_expects_no_camera(text: str) -> None:
    hints = detect_intents(text)
    tools = {t for h in hints for t in h.expected_tools}
    assert "camera" not in tools, text
    assert "vision" not in {h.kind for h in hints}, text


def test_veto_callers_keep_the_old_answer() -> None:
    """Default stays the raw search, so the desk and vision vetoes do not move."""
    assert mentions_camera_look("no need to look at this")
    assert mentions_camera_look("look at this")


def test_real_looks_still_fire() -> None:
    for text in (
        "look at this",
        "ok no need to rush. look at this",
        "what do you see on the camera",
        "look at the webcam",
    ):
        look = classify_look(text, dock_live=True)
        assert look is not None, text
        assert look.act == "identify", text
        assert mentions_camera_look(text, unnegated=True), text
    tools = {t for h in detect_intents("look at this") for t in h.expected_tools}
    assert "camera" in tools
    assert "vision" in {h.kind for h in detect_intents("look at this")}
    translate = classify_look("translate this", dock_live=True)
    assert translate is not None and translate.act == "translate"
