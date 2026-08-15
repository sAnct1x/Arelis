"""Image path helpers + chat_fast_path re-arm for vision/image turns."""

from __future__ import annotations

from pathlib import Path

from arelis.core.agent_loop import should_offer_tools
from arelis.core.claims import detect_exactness_need, detect_vision_ask
from arelis.core.image_refs import (
    CAMERA_FRESH_S,
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
