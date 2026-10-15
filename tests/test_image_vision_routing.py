"""Image path helpers + chat_fast_path re-arm for vision/image turns."""

from __future__ import annotations

from arelis.attachments import (
    format_attachments_block,
    route_tool,
    wants_image_edit,
    wants_image_restyle,
    wants_image_surgical,
)
from arelis.core.agent_loop import (
    should_redirect_wander_to_sms,
)
from arelis.core.image_refs import (
    mentions_camera_look,
)
from arelis.core.preflight import detect_intents
from arelis.core.skills import select_skill_ids
from arelis.core.sms_complete import looks_like_image_gen


def test_mentions_camera_look() -> None:
    assert mentions_camera_look("look at the camera")
    assert mentions_camera_look("look at the desk camera")
    assert mentions_camera_look("look at the room webcam")
    assert mentions_camera_look("What do you see?")
    assert mentions_camera_look("check the webcam feed")
    assert mentions_camera_look("Look at this. What is it?")
    assert not mentions_camera_look("describe the image you just generated")
    assert not mentions_camera_look("hello there")
    assert not mentions_camera_look("look at the book")


def _attach_image_turn(ask: str) -> str:
    block = format_attachments_block(
        [
            {
                "path": r"C:\Users\you\Documents\Arelis\data\drops\20260817\paste.png",
                "kind": "image",
            }
        ],
        user_text=ask,
    )
    return f"{block}\n\n{ask}"


def test_vision_does_not_redirect_to_sms_when_sms_is_stale_expected() -> None:
    """Calling vision while a leftover SMS expected-set exists must not rewrite."""
    assert not should_redirect_wander_to_sms("vision", {"send_sms"})
    assert not should_redirect_wander_to_sms("ocr", {"send_sms"})
    assert not should_redirect_wander_to_sms("image", {"send_sms"})
    assert not should_redirect_wander_to_sms("image_edit", {"send_sms"})
    assert not should_redirect_wander_to_sms("camera", {"send_sms"})
    assert should_redirect_wander_to_sms("web_search", {"send_sms"})


def test_vibrant_thumbnail_expects_image_edit_not_generate() -> None:
    """7.2: edit the attached pixels; do not force Comfy generate."""
    ask = "Make this more vibrant and resize it for a YouTube thumbnail."
    text = _attach_image_turn(ask)
    assert wants_image_edit(ask)
    assert not looks_like_image_gen(ask)
    assert not looks_like_image_gen(text)
    hints = detect_intents(text)
    tools = {t for h in hints for t in h.expected_tools}
    kinds = [h.kind for h in hints]
    assert "image_edit" in tools
    assert "image" not in tools
    assert "image_gen" not in kinds
    ids = select_skill_ids(
        ask,
        available_tools={"image", "image_edit", "vision", "web_search"},
    )
    assert "image_edit" in ids
    assert "image" not in ids


def _last_image_history() -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": "saved to outputs/images/arelis_00021_.png",
            "note": "",
        }
    ]


def _assert_routes_image(ask: str, *, gen: bool = True) -> None:
    assert route_tool("image", ask) == "image"
    assert looks_like_image_gen(ask) is gen
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    assert "image" in tools
    assert "image_edit" not in tools
    assert "send_sms" not in tools
    assert "calculator" not in tools
    ids = select_skill_ids(
        ask,
        available_tools={"image", "image_edit", "vision", "web_search", "calculator"},
    )
    assert "image" in ids
    assert "image_edit" not in ids


def _assert_routes_image_edit(ask: str) -> None:
    assert wants_image_edit(ask)
    assert not wants_image_restyle(ask)
    assert not wants_image_surgical(ask)
    assert not looks_like_image_gen(ask)
    assert route_tool("image", ask) == "image_edit"
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    assert "image_edit" in tools
    assert "image" not in tools
    assert "send_sms" not in tools
    assert "calculator" not in tools
    ids = select_skill_ids(
        ask,
        available_tools={"image", "image_edit", "vision", "web_search", "calculator"},
    )
    assert "image_edit" in ids
    assert "image" not in ids


