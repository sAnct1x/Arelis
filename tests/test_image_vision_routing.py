"""Image path helpers + chat_fast_path re-arm for vision/image turns."""

from __future__ import annotations

from pathlib import Path

from arelis.attachments import (
    attach_typed_images,
    format_attachments_block,
    image_path_tokens,
    refuse_see_tool,
    route_tool,
    stage_typed_images,
    wants_image_edit,
    wants_image_restyle,
    wants_image_surgical,
    wants_image_text,
)
from arelis.core.agent_loop import (
    should_redirect_wander_to_sms,
)
from arelis.core.image_refs import (
    mentions_camera_look,
)
from arelis.core.plan_nudge import select_plan
from arelis.core.preflight import _VISION, detect_intents
from arelis.core.skills import select_skill_ids
from arelis.core.sms_complete import looks_like_image_gen
from arelis.core.turn_context import TurnContext
from arelis.core.turn_scratch import named_tools_owed


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


# 1x1 PNG. Same bytes the paperclip bench uses.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)

_MENU = {"image", "ocr", "plot", "vision", "camera", "web_search"}


class _OwedLoop:
    def __init__(self) -> None:
        self.tools_used: set[str] = set()


def _owed(text: str, menu: set[str] | None = None) -> list[str]:
    ctx = TurnContext(text=text, role="fast")
    ctx.available_all = set(menu or _MENU)
    return named_tools_owed(_OwedLoop(), ctx)


def _tools(text: str) -> set[str]:
    return {tool for hint in detect_intents(text) for tool in hint.expected_tools}


def test_typed_image_path_is_vision_not_ocr_or_generate(tmp_path: Path) -> None:
    """A path typed in the ask is looked at, the way a paperclip drop is.

    'what is in C:/.../shapes.png' and 'describe ./plot.png' used to miss the
    see-pattern, so the turn had no vision intent. The word image, and a
    filename stem like plot.png, were then owed as tools.
    """
    windows = "what is in C:/Users/me/Pictures/shapes.png"
    relative = "describe ./plot.png"
    for ask in (windows, relative):
        assert "vision" in _tools(ask)
        assert "image" not in _tools(ask)
        assert "ocr" not in _tools(ask)
        assert not looks_like_image_gen(ask)
        owed = _owed(ask)
        assert "image" not in owed
        assert "ocr" not in owed
        assert "plot" not in owed

    assert image_path_tokens("describe https://example.com/a.png") == []
    assert image_path_tokens("What's in outputs/images/demo.png?") == []
    assert stage_typed_images(windows, drops_root=tmp_path / "missing") == []

    shapes = tmp_path / "shapes.png"
    plot = tmp_path / "plot.png"
    shapes.write_bytes(_PNG)
    plot.write_bytes(_PNG)
    drops = tmp_path / "drops"

    seen, rows = attach_typed_images(
        f"what is in {shapes.as_posix()}",
        drops_root=drops,
    )
    assert len(rows) == 1
    assert rows[0]["kind"] == "image"
    assert "→ vision" in seen
    blocked = stage_typed_images(
        f"what is in {shapes.as_posix()}",
        drops_root=tmp_path / "blocked",
        allow=lambda _path: False,
    )
    assert blocked == []
    plan = select_plan(seen)
    assert plan is not None
    assert plan.id == "attach_vision"
    assert plan.steps == ("vision",)

    described, desc_rows = attach_typed_images(
        "describe ./plot.png",
        bases=(tmp_path,),
        drops_root=drops,
    )
    assert len(desc_rows) == 1
    assert desc_rows[0]["kind"] == "image"
    assert "→ vision" in described
    desc_plan = select_plan(described)
    assert desc_plan is not None and desc_plan.steps == ("vision",)

    assert "image" not in _owed("what is in this image")
    assert "image" not in _owed("describe this image")
    assert "image" not in _owed("read the text in this image")
    assert route_tool("image", "read the text in this image") == "ocr"

    ocr_path = f"read the text in {shapes.as_posix()}"
    assert wants_image_text(ocr_path)
    assert route_tool("image", ocr_path) == "ocr"
    assert _VISION.search(ocr_path) is None
    ocr_ids = select_skill_ids(
        ocr_path,
        available_tools={"ocr", "vision", "image", "docs", "web_search"},
    )
    ocr_plan = select_plan(ocr_path, skill_ids=ocr_ids)
    assert ocr_plan is not None and ocr_plan.id == "ocr"
    assert "image" not in _owed(ocr_path)

    generate = "generate an image of a lighthouse"
    assert looks_like_image_gen(generate)
    assert "image" in _tools(generate)
    assert "image" in _owed(generate)
    assert "plot" in _owed("plot the data to plot.png")
    assert "image" in _owed("generate image.png")

    assert refuse_see_tool("image", relative)
    assert refuse_see_tool("ocr", relative)
    assert refuse_see_tool("vision", relative) is None
    assert refuse_see_tool("image", generate) is None
    assert refuse_see_tool("ocr", ocr_path) is None
    assert "—" not in (refuse_see_tool("image", relative) or "")
