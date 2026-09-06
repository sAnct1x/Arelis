"""Image path helpers + chat_fast_path re-arm for vision/image turns."""

from __future__ import annotations

from pathlib import Path

from arelis.attachments import (
    format_attachments_block,
    route_tool,
    wants_image_edit,
    wants_image_restyle,
    wants_image_surgical,
    wants_image_variations,
)
from arelis.core.agent_loop import (
    should_offer_tools,
    should_redirect_wander_to_sms,
    turn_expects_tool_round,
)
from arelis.core.claims import detect_exactness_need, detect_vision_ask
from arelis.core.image_refs import (
    CAMERA_FRESH_S,
    fill_image_edit_args,
    fill_image_gen_args,
    fill_vision_args,
    latest_camera_image_file,
    latest_generated_image_path,
    mentions_camera_look,
    path_from_text,
)
from arelis.core.preflight import detect_intents
from arelis.core.skills import select_skill_ids
from arelis.core.sms_complete import looks_like_image_gen


def test_describe_the_image_is_vision_ask() -> None:
    phrases = (
        "yes, please describe the image you just generated",
        "describe the image",
        "Describe this image",
    )
    for phrase in phrases:
        assert detect_vision_ask(phrase), phrase
        need = detect_exactness_need(phrase)
        assert need.needs_vision, phrase
        assert "vision" in need.kinds


def test_generate_the_image_matches() -> None:
    assert looks_like_image_gen("no, that is good enough, generate the image")
    assert looks_like_image_gen(
        "no, i want you to generate a new image of a cute puppy "
        "but make it look happier and less sad"
    )


def test_new_image_phrases_match_image_gen() -> None:
    phrases = (
        "generate a new image of a cute puppy but make it look happier",
        "make a new image with a less sad puppy",
        "generate an image of a cute puppy",
        "another image of a happy puppy",
    )
    for phrase in phrases:
        assert looks_like_image_gen(phrase), phrase


def test_image_gen_preflight_expects_image_tool() -> None:
    hints = detect_intents(
        "generate a new image of a cute puppy but make it look happier"
    )
    assert any(h.kind == "image_gen" for h in hints)
    assert "image" in {t for h in hints for t in h.expected_tools}
    assert not any(h.kind == "sms_send" for h in hints)


def test_vision_preflight_on_describe_the_image() -> None:
    history = [
        {
            "role": "assistant",
            "content": (
                "Image saved to C:\\Users\\you\\Documents\\Arelis\\"
                "outputs\\images\\arelis_00008_.png"
            ),
            "note": "[tools used this turn: image outputs/images/arelis_00008_.png]",
        }
    ]
    hints = detect_intents(
        "yes, please describe the image you just generated",
        history=history,
    )
    assert any(h.kind == "vision" for h in hints)
    nudge = next(h.nudge for h in hints if h.kind == "vision")
    assert "arelis_00008" in nudge or "outputs/images" in nudge


def test_skill_selects_image_on_new_image_ask() -> None:
    ids = select_skill_ids(
        "generate a new image of a cute puppy but make it look happier",
        available_tools={"image", "vision", "web_search"},
    )
    assert "image" in ids


def test_skill_selects_vision_on_describe_the_image() -> None:
    ids = select_skill_ids(
        "describe the image you just generated",
        available_tools={"image", "vision", "web_search"},
    )
    assert "vision" in ids


def test_chat_fast_path_rearms_for_vision_exactness() -> None:
    need = detect_exactness_need("describe the image you just generated")
    assert should_offer_tools(
        chat_fast_path=True,
        skill_ids=[],
        preflight_kinds=[],
        research_mode=False,
        expected_tools=set(),
        exact_need=need,
        wants_fresh_page=False,
        active_plan=None,
    )


def test_chat_fast_path_rearms_for_image_preflight() -> None:
    need = detect_exactness_need("hello there")
    assert should_offer_tools(
        chat_fast_path=True,
        skill_ids=[],
        preflight_kinds=["image_gen"],
        research_mode=False,
        expected_tools={"image"},
        exact_need=need,
        wants_fresh_page=False,
        active_plan=None,
    )


def test_how_are_you_today_is_not_a_news_ask() -> None:
    from arelis.core.agent_loop import wants_fresh_page_ask

    assert not wants_fresh_page_ask("how are you today?")
    assert not wants_fresh_page_ask("hello")
    assert wants_fresh_page_ask("what happened in the news today?")
    assert wants_fresh_page_ask("latest headlines")


def test_shipped_chat_fast_path_is_off_so_the_prefix_cache_survives() -> None:
    """A greeting that omits schemas overwrites the startup seed.

    The dump that caught this: hold_paint=0 on 'how are you', then 41s of
    prefill on the next question that needed tools.
    """
    import yaml

    shipped = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "arelis" / "config" / "default.yaml")
        .read_text(encoding="utf-8")
    )
    assert shipped["agent"]["chat_fast_path"] is False


def test_chat_fast_path_still_skips_pure_chat() -> None:
    need = detect_exactness_need("thanks, that helps")
    assert not should_offer_tools(
        chat_fast_path=True,
        skill_ids=[],
        preflight_kinds=[],
        research_mode=False,
        expected_tools=set(),
        exact_need=need,
        wants_fresh_page=False,
        active_plan=None,
    )


def test_chat_fast_path_skips_a_clock_ask() -> None:
    """`what` used to web-fallback, which re-armed every schema (~11k tokens)."""
    from arelis.core.plan_nudge import select_plan
    from arelis.core.skills import select_skill_ids

    text = "what time is it"
    tools = {"web_search", "scrape", "web_fetch", "weather", "calculator"}
    ids = select_skill_ids(text, available_tools=tools)
    plan = select_plan(text, skill_ids=ids)
    need = detect_exactness_need(text)
    assert "web" not in ids
    assert plan is None
    assert not should_offer_tools(
        chat_fast_path=True,
        skill_ids=ids,
        preflight_kinds=[],
        research_mode=False,
        expected_tools=set(),
        exact_need=need,
        wants_fresh_page=False,
        active_plan=plan,
    )


def test_web_fallback_does_not_count_as_a_tool_round() -> None:
    """Schemas stay on (chat_fast_path off). Hold/hint must not follow the floor."""
    from arelis.core.skills import select_skill_ids_detailed

    need = detect_exactness_need("Who is this")
    ids, fallback = select_skill_ids_detailed(
        "Who is this",
        available_tools={"web_search", "scrape", "web_fetch"},
    )
    plan_ids = () if fallback else ids
    assert fallback is True
    assert should_offer_tools(
        chat_fast_path=False,
        skill_ids=ids,
        preflight_kinds=[],
        research_mode=False,
        expected_tools=set(),
        exact_need=need,
        wants_fresh_page=False,
        active_plan=None,
    )
    assert not turn_expects_tool_round(
        skill_ids=plan_ids,
        preflight_kinds=[],
        research_mode=False,
        expected_tools=set(),
        exact_need=need,
        wants_fresh_page=False,
        active_plan=None,
    )


def test_weather_still_expects_a_tool_round() -> None:
    need = detect_exactness_need("What's the weather today?")
    assert turn_expects_tool_round(
        skill_ids=("weather",),
        preflight_kinds=["weather"],
        research_mode=False,
        expected_tools={"weather"},
        exact_need=need,
        wants_fresh_page=False,
        active_plan=object(),
    )


def test_fill_vision_args_from_history_path(tmp_path: Path) -> None:
    history = [
        {
            "role": "assistant",
            "content": f"saved to {tmp_path / 'outputs' / 'images' / 'arelis_00008_.png'}",
            "note": "",
        }
    ]
    # path_from_text needs outputs/images in the string
    history = [
        {
            "role": "assistant",
            "content": "saved to outputs/images/arelis_00008_.png",
            "note": "",
        }
    ]
    assert path_from_text(history[0]["content"]) == "outputs/images/arelis_00008_.png"
    filled = fill_vision_args({}, history=history)
    assert filled["path"] == "outputs/images/arelis_00008_.png"


def test_latest_from_disk(tmp_path: Path, monkeypatch) -> None:
    images = tmp_path / "outputs" / "images"
    images.mkdir(parents=True)
    older = images / "arelis_00001_.png"
    newer = images / "arelis_00009_.png"
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    import os
    import time

    now = time.time()
    os.utime(older, (now - 10, now - 10))
    os.utime(newer, (now, now))
    path = latest_generated_image_path(history=[], images_dir=images)
    assert path is not None
    assert path.endswith("arelis_00009_.png") or "arelis_00009" in path


def test_mentions_camera_look() -> None:
    assert mentions_camera_look("look at the camera")
    assert mentions_camera_look("What do you see?")
    assert mentions_camera_look("check the webcam feed")
    assert mentions_camera_look("Look at this. What is it?")
    assert not mentions_camera_look("describe the image you just generated")
    assert not mentions_camera_look("hello there")


def test_latest_camera_image_file_age(tmp_path: Path) -> None:
    import os
    import time

    images = tmp_path / "outputs" / "images"
    images.mkdir(parents=True)
    stale = images / "camera_old.jpg"
    fresh = images / "camera_new.jpg"
    stale.write_bytes(b"old")
    fresh.write_bytes(b"new")
    now = time.time()
    os.utime(stale, (now - 120, now - 120))
    os.utime(fresh, (now - 5, now - 5))
    hit = latest_camera_image_file(images_dir=images, max_age_s=CAMERA_FRESH_S)
    assert hit is not None
    assert "camera_new" in hit
    os.utime(fresh, (now - 120, now - 120))
    assert latest_camera_image_file(images_dir=images, max_age_s=30) is None


def test_fill_vision_args_prefers_camera_on_look(tmp_path: Path, monkeypatch) -> None:
    images = tmp_path / "outputs" / "images"
    images.mkdir(parents=True)
    cam = images / "camera_ask.jpg"
    gen = images / "arelis_00001_.png"
    cam.write_bytes(b"cam")
    gen.write_bytes(b"gen")
    monkeypatch.setattr(
        "arelis.core.image_refs.latest_camera_image_file",
        lambda **_kw: "outputs/images/camera_ask.jpg",
    )
    filled = fill_vision_args({}, user_text="look at the camera")
    assert filled["path"] == "outputs/images/camera_ask.jpg"
    # Explicit path in user text wins
    filled2 = fill_vision_args(
        {},
        user_text="look at outputs/images/camera_explicit.jpg please",
    )
    assert filled2["path"] == "outputs/images/camera_explicit.jpg"
    # Existing path arg untouched
    filled3 = fill_vision_args(
        {"path": "outputs/images/keep.png"},
        user_text="look at the camera",
    )
    assert filled3["path"] == "outputs/images/keep.png"


def test_skill_selects_vision_on_camera_look() -> None:
    ids = select_skill_ids(
        "look at the camera",
        available_tools={"image", "vision", "camera", "web_search"},
    )
    assert "vision" in ids


def test_vision_ask_on_camera_look() -> None:
    assert detect_vision_ask("look at the webcam")
    assert detect_vision_ask("what do you see")


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


def test_whats_in_this_image_expects_vision_not_sms() -> None:
    """7.1: a pasted screenshot + 'what's in this image?' is vision, never SMS."""
    ask = "what's in this image?"
    text = _attach_image_turn(ask)
    need = detect_exactness_need(ask)
    assert need.needs_vision
    assert "vision" in need.kinds
    hints = detect_intents(text)
    tools = {t for h in hints for t in h.expected_tools}
    kinds = [h.kind for h in hints]
    assert "vision" in tools
    assert "send_sms" not in tools
    assert "sms_send" not in kinds


def test_what_in_this_with_image_is_not_sms() -> None:
    """Shorter follow-up on a pasted shot must not arm send_sms."""
    text = _attach_image_turn("what in this?")
    hints = detect_intents(text)
    tools = {t for h in hints for t in h.expected_tools}
    assert "vision" in tools
    assert "send_sms" not in tools


def test_hide_contacts_on_sms_keeps_lookup() -> None:
    from arelis.core.agent_loop import _hide_daily_wander

    visible = {"send_sms", "contacts", "weather", "browser", "web_search"}
    sms = _hide_daily_wander(visible, {"send_sms"})
    assert "send_sms" in sms
    assert "contacts" not in sms
    assert "browser" not in sms
    lookup = _hide_daily_wander(visible, {"contacts"})
    assert "contacts" in lookup
    agenda = _hide_daily_wander(visible | {"agenda"}, {"agenda"})
    assert "contacts" in agenda


def test_vision_does_not_redirect_to_sms_when_sms_is_stale_expected() -> None:
    """Calling vision while a leftover SMS expected-set exists must not rewrite."""
    assert not should_redirect_wander_to_sms("vision", {"send_sms"})
    assert not should_redirect_wander_to_sms("ocr", {"send_sms"})
    assert not should_redirect_wander_to_sms("image", {"send_sms"})
    assert not should_redirect_wander_to_sms("image_edit", {"send_sms"})
    assert not should_redirect_wander_to_sms("camera", {"send_sms"})
    assert should_redirect_wander_to_sms("web_search", {"send_sms"})


def test_stale_sms_draft_does_not_revive_on_vision_ask() -> None:
    history = [
        {"role": "user", "content": "text Alex that I am running late"},
        {"role": "assistant", "content": "What should the message say?"},
    ]
    hints = detect_intents(_attach_image_turn("what's in this image?"), history=history)
    assert "sms_send" not in [h.kind for h in hints]


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


def test_spiral_galaxy_generate_still_expects_image() -> None:
    """7.3 must stay generate — do not treat it as an edit."""
    ask = "generate an image of a spiral galaxy"
    assert looks_like_image_gen(ask)
    assert not wants_image_edit(ask)
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    assert "image" in tools
    assert "image_edit" not in tools


def test_fill_vision_args_uses_paste_not_generated() -> None:
    """A homework photo this turn must beat a leftover generated image in history."""
    ask = "answer the question in this photo"
    text = _attach_image_turn(ask)
    history = [
        {
            "role": "assistant",
            "content": "saved to outputs/images/arelis_00008_.png",
            "note": "",
        }
    ]
    filled = fill_vision_args({}, history=history, user_text=text)
    path = str(filled.get("path") or "").replace("\\", "/")
    assert "paste.png" in path
    assert "arelis_00008" not in path
    assert detect_vision_ask(ask)
    hints = detect_intents(text)
    tools = {t for h in hints for t in h.expected_tools}
    assert "vision" in tools
    assert "send_sms" not in tools


def test_add_text_overlay_expects_image_edit_not_sms() -> None:
    """The jellyfish follow-up: overlay glyphs, do not inject send_sms."""
    ask = (
        "I want you to now edit the picture you just created, and I want you "
        "to add text right in the middle that says Arelis, centered perfectly"
    )
    assert wants_image_edit(ask)
    history = [
        {
            "role": "assistant",
            "content": (
                "Image ready — open in Workspace "
                "(C:\\Users\\origi\\Documents\\Arelis\\outputs\\images\\arelis_00021_.png)."
            ),
            "note": "",
        }
    ]
    filled = fill_image_edit_args({}, history=history, user_text=ask)
    path = str(filled.get("path") or "").replace("\\", "/")
    assert "arelis_00021_.png" in path
    assert filled.get("text") == "Arelis"
    assert filled.get("text_align") == "center"
    hints = detect_intents(ask, history=history)
    tools = {t for h in hints for t in h.expected_tools}
    kinds = [h.kind for h in hints]
    assert "image_edit" in tools
    assert "sms_send" not in kinds
    assert "send_sms" not in tools


def test_watercolor_restyle_is_image_not_pillow() -> None:
    ask = "make this look like a watercolor"
    assert wants_image_restyle(ask)
    assert not wants_image_edit(ask)
    assert looks_like_image_gen(ask)
    assert route_tool("image", ask) == "image"
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    assert "image" in tools
    assert "image_edit" not in tools
    ids = select_skill_ids(
        ask,
        available_tools={"image", "image_edit", "vision", "web_search"},
    )
    assert "image" in ids
    assert "image_edit" not in ids


def test_turn_into_thumbnail_stays_image_edit() -> None:
    ask = "turn this into a YouTube thumbnail"
    assert wants_image_edit(ask)
    assert not wants_image_restyle(ask)
    assert not looks_like_image_gen(ask)
    assert route_tool("image", ask) == "image_edit"


def test_rotate_this_is_image_edit() -> None:
    ask = "rotate this 90 degrees"
    assert wants_image_edit(ask)
    assert not looks_like_image_gen(ask)
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    assert "image_edit" in tools


def test_draw_me_matches_image_gen() -> None:
    assert looks_like_image_gen("draw me a picture of a red fox")


def test_fill_image_gen_args_picks_style_and_last_file() -> None:
    ask = "make the picture you just created look like a watercolor"
    history = [
        {
            "role": "assistant",
            "content": "saved to outputs/images/arelis_00021_.png",
            "note": "",
        }
    ]
    filled = fill_image_gen_args({}, history=history, user_text=ask)
    assert filled.get("style") == "watercolor"
    assert filled.get("denoise") == 0.55
    path = str(filled.get("path") or "").replace("\\", "/")
    assert "arelis_00021_.png" in path


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


def test_four_versions_is_image_n4() -> None:
    for ask in (
        "four versions of a red fox",
        "give me four variations",
        "another four",
        "n=4 of a spiral galaxy",
    ):
        assert wants_image_variations(ask), ask
        assert not wants_image_edit(ask), ask
        _assert_routes_image(ask)
        filled = fill_image_gen_args({}, user_text=ask)
        assert filled.get("n") == 4, ask


def test_watercolor_style_of_still_restyle() -> None:
    ask = "in the style of a watercolor"
    assert wants_image_restyle(ask)
    assert not wants_image_edit(ask)
    _assert_routes_image(ask)
    filled = fill_image_gen_args({}, history=_last_image_history(), user_text=ask)
    assert filled.get("style") == "watercolor"
    assert filled.get("denoise") == 0.55


def test_remove_background_is_image_surgical() -> None:
    for ask in (
        "remove the background",
        "cut out the background",
    ):
        assert wants_image_surgical(ask), ask
        assert not wants_image_edit(ask), ask
        assert looks_like_image_gen(ask), ask
        _assert_routes_image(ask)
        filled = fill_image_gen_args(
            {}, history=_last_image_history(), user_text=ask
        )
        assert filled.get("remove_background") is True, ask
        path = str(filled.get("path") or "").replace("\\", "/")
        assert "arelis_00021_.png" in path, ask


def test_outpaint_uncrop_is_image_surgical() -> None:
    for ask in (
        "extend the canvas",
        "outpaint this",
        "uncrop the picture",
    ):
        assert wants_image_surgical(ask), ask
        assert not wants_image_edit(ask), ask
        _assert_routes_image(ask)
        filled = fill_image_gen_args(
            {}, history=_last_image_history(), user_text=ask
        )
        assert filled.get("outpaint") == "all", ask
        path = str(filled.get("path") or "").replace("\\", "/")
        assert "arelis_00021_.png" in path, ask


def test_mask_region_is_image_surgical() -> None:
    cases = (
        ("remove the left of the picture", "left"),
        ("change the right of the picture", "right"),
        ("change the top of the image", "top"),
        ("remove the bottom of the photo", "bottom"),
        ("change the center of the picture", "center"),
    )
    for ask, region in cases:
        assert wants_image_surgical(ask), ask
        assert not wants_image_edit(ask), ask
        assert not wants_image_restyle(ask), ask
        _assert_routes_image(ask)
        filled = fill_image_gen_args(
            {}, history=_last_image_history(), user_text=ask
        )
        assert filled.get("mask_region") == region, ask
        path = str(filled.get("path") or "").replace("\\", "/")
        assert "arelis_00021_.png" in path, ask


def test_upscale_is_image_edit_scale_2() -> None:
    for ask in (
        "upscale this",
        "make it bigger",
        "make this 2x",
    ):
        _assert_routes_image_edit(ask)
        filled = fill_image_edit_args(
            {}, history=_last_image_history(), user_text=ask
        )
        assert filled.get("scale") == 2, ask
        path = str(filled.get("path") or "").replace("\\", "/")
        assert "arelis_00021_.png" in path, ask


def test_crop_half_is_image_edit_not_restyle() -> None:
    cases = (
        ("crop the left half", "left"),
        ("crop the right half", "right"),
        ("crop to the center", "center"),
    )
    for ask, crop in cases:
        _assert_routes_image_edit(ask)
        filled = fill_image_edit_args(
            {}, history=_last_image_history(), user_text=ask
        )
        assert filled.get("crop") == crop, ask
        path = str(filled.get("path") or "").replace("\\", "/")
        assert "arelis_00021_.png" in path, ask


def test_same_seed_again_reuses_sidecar(tmp_path, monkeypatch) -> None:
    ask = "do that again"
    assert looks_like_image_gen(ask)
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    folder = tmp_path / "outputs" / "images"
    folder.mkdir(parents=True)
    png = folder / "arelis_00021_.png"
    png.write_bytes(b"\x89PNG")
    from arelis.tools.image_meta import write_sidecar

    write_sidecar(
        png,
        prompt="a red fox",
        negative="blurry",
        seed=99,
        checkpoint="demo.safetensors",
        width=768,
        height=768,
        style="cinematic",
        mode="txt2img",
        source="",
        denoise=1.0,
        n=1,
    )
    filled = fill_image_gen_args(
        {"prompt": ask},
        history=_last_image_history(),
        user_text=ask,
    )
    assert filled.get("seed") == 99
    assert filled.get("prompt") == "a red fox"
    assert filled.get("style") == "cinematic"


def test_pixel_ops_stay_image_edit() -> None:
    for ask in (
        "rotate this 90 degrees",
        "flip it horizontally",
        "make this grayscale",
        "blur this a little",
        "make this more vibrant",
        "turn this into a YouTube thumbnail",
        "add text right in the middle that says Arelis",
    ):
        _assert_routes_image_edit(ask)
