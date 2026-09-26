"""The tool that was missing when someone asked for a YouTube thumbnail.

The ask was "make this more vibrant and resize it to 1280 x 720". There was no
tool that could do it, so three wrong ones were tried in turn: vision (which can
only look), image (which invented a different picture at the right size), and
finally the calculator, forced in because "1280 x 720" reads as arithmetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from arelis.core.tool_subset import filter_tool_names
from arelis.tools import build_tool_registry
from arelis.tools.base import capability_class
from arelis.tools.image_edit import SIZE_PRESETS, ImageEditTool
from arelis.workspace import WorkspaceRoots


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A workspace root plus a separate data root, as an install has."""
    root = tmp_path / "project"
    root.mkdir()
    data = tmp_path / "appdata"
    (data / "data" / "drops").mkdir(parents=True)
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "project", "path": str(root)}]}}
    )
    return root, data, workspace


@pytest.fixture
def tool(project):
    _root, _data, workspace = project
    return ImageEditTool(workspace)


def _write(path, size, colour=(120, 60, 30)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    return path


@pytest.mark.asyncio
async def test_the_ask_that_had_no_tool(project, tool) -> None:
    """Vibrance and a thumbnail size, in one call, from a 16:9 source."""
    root, _data, _ws = project
    _write(root / "shot.png", (2560, 1440))

    result = await tool.run(
        path="project:shot.png", preset="youtube_thumbnail", vibrance=1.3
    )

    assert result.ok, result.output
    assert result.data["result_px"] == [1280, 720]
    assert result.data["cropped"] is False
    with Image.open(result.data["abs_path"]) as out:
        assert out.size == (1280, 720)
    assert "1280x720" in result.output
    assert "+30%" in result.output


@pytest.mark.asyncio
async def test_the_original_is_never_touched(project, tool) -> None:
    """The input is usually the only copy of something somebody sent you."""
    root, _data, _ws = project
    source = _write(root / "only-copy.png", (800, 600))
    before = source.read_bytes()

    result = await tool.run(path="project:only-copy.png", preset="youtube_thumbnail")

    assert result.ok
    assert source.read_bytes() == before
    assert result.data["abs_path"] != str(source)


@pytest.mark.asyncio
async def test_a_pasted_attachment_resolves_on_an_installed_layout(project, tool) -> None:
    """data/drops sits under the data root, not inside any project.

    From a checkout those are the same directory, so resolving a paste against
    the workspace alone looks fine and fails on every installed copy.
    """
    _root, data, _ws = project
    _write(data / "data" / "drops" / "20260817" / "paste.png", (1600, 900))

    result = await tool.run(
        path="data/drops/20260817/paste.png", preset="youtube_thumbnail"
    )

    assert result.ok, result.output
    assert result.data["result_px"] == [1280, 720]


@pytest.mark.asyncio
async def test_a_different_shape_is_cropped_and_says_so(project, tool) -> None:
    """Centre is the only defensible guess, so the reply admits it guessed."""
    root, _data, _ws = project
    _write(root / "four-three.png", (1600, 1200))

    result = await tool.run(path="project:four-three.png", preset="youtube_thumbnail")

    assert result.ok
    assert result.data["cropped"] is True
    assert result.data["result_px"] == [1280, 720]
    assert "cropped" in result.output.lower()


@pytest.mark.asyncio
async def test_contain_pads_instead_of_cutting(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "four-three.png", (1600, 1200))

    result = await tool.run(
        path="project:four-three.png", width=1280, height=720, fit="contain"
    )

    assert result.ok
    assert result.data["cropped"] is False
    assert result.data["result_px"] == [1280, 720]


@pytest.mark.asyncio
async def test_stretch_distorts_on_request(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "square.png", (1000, 1000))

    result = await tool.run(
        path="project:square.png", width=1280, height=720, fit="stretch"
    )

    assert result.ok
    assert result.data["cropped"] is False
    assert result.data["result_px"] == [1280, 720]


@pytest.mark.asyncio
async def test_adjusting_without_resizing_keeps_the_size(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "shot.png", (640, 480))

    result = await tool.run(path="project:shot.png", vibrance=1.4)

    assert result.ok
    assert result.data["result_px"] == [640, 480]
    assert "+40%" in result.output


@pytest.mark.asyncio
async def test_a_call_that_changes_nothing_is_refused_with_the_options(tool, project) -> None:
    """Silently copying a file would look like it worked."""
    root, _data, _ws = project
    _write(root / "shot.png", (640, 480))

    result = await tool.run(path="project:shot.png")

    assert not result.ok
    assert "preset=youtube_thumbnail" in result.output
    assert "vibrance" in result.output
    assert "crop=" in result.output
    assert "scale=2" in result.output
    assert "pad=" in result.output
    assert "warmth=" in result.output


@pytest.mark.asyncio
async def test_one_dimension_is_ambiguous_and_says_why(tool, project) -> None:
    root, _data, _ws = project
    _write(root / "shot.png", (640, 480))

    result = await tool.run(path="project:shot.png", width=1280)

    assert not result.ok
    assert "both width and height" in result.output


@pytest.mark.asyncio
async def test_an_absurd_factor_is_clamped_rather_than_obeyed(tool, project) -> None:
    """A model that asks for vibrance 40 gets a picture, not a colour field."""
    root, _data, _ws = project
    _write(root / "shot.png", (320, 240))

    result = await tool.run(path="project:shot.png", vibrance=40)

    assert result.ok
    assert result.data["adjustments"]["vibrance"] == 3.0


@pytest.mark.asyncio
async def test_a_size_beyond_the_tools_purpose_is_refused(tool, project) -> None:
    root, _data, _ws = project
    _write(root / "shot.png", (320, 240))

    result = await tool.run(path="project:shot.png", width=90000, height=90000)

    assert not result.ok
    assert "larger than" in result.output


@pytest.mark.asyncio
async def test_an_unknown_preset_lists_the_known_ones(tool, project) -> None:
    root, _data, _ws = project
    _write(root / "shot.png", (320, 240))

    result = await tool.run(path="project:shot.png", preset="billboard")

    assert not result.ok
    for name in SIZE_PRESETS:
        assert name in result.output


@pytest.mark.asyncio
async def test_a_path_outside_every_readable_root_is_refused(tool, tmp_path) -> None:
    outside = tmp_path / "elsewhere" / "secret.png"
    _write(outside, (100, 100))

    result = await tool.run(path=str(outside), preset="youtube_thumbnail")

    assert not result.ok
    assert "outside" in result.output


@pytest.mark.asyncio
async def test_a_file_that_is_not_an_image_is_refused(tool, project) -> None:
    root, _data, _ws = project
    (root / "notes.md").write_text("not pixels", encoding="utf-8")

    result = await tool.run(path="project:notes.md", preset="youtube_thumbnail")

    assert not result.ok
    assert "Unsupported image type" in result.output


@pytest.mark.asyncio
async def test_every_failure_carries_the_tag_the_replan_notice_reads(tool, project) -> None:
    root, _data, _ws = project
    _write(root / "shot.png", (320, 240))

    for kwargs in (
        {"path": "project:shot.png"},
        {"path": "project:shot.png", "preset": "nope"},
        {"path": "project:missing.png", "preset": "youtube_thumbnail"},
        {"path": "project:shot.png", "fit": "sideways", "preset": "youtube_thumbnail"},
        {"path": "project:shot.png", "format": "tiff", "preset": "youtube_thumbnail"},
    ):
        result = await tool.run(**kwargs)
        assert not result.ok, kwargs
        assert result.output.startswith("[fail:image_edit]"), result.output


@pytest.mark.asyncio
async def test_jpg_output_is_written_as_jpg(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "shot.png", (800, 450))

    result = await tool.run(path="project:shot.png", width=640, height=360, format="jpg")

    assert result.ok
    assert result.data["path"].endswith(".jpg")
    with Image.open(result.data["abs_path"]) as out:
        assert out.format == "JPEG"


@pytest.mark.asyncio
async def test_two_edits_of_one_file_do_not_overwrite_each_other(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "shot.png", (800, 450))

    first = await tool.run(path="project:shot.png", preset="youtube_thumbnail")
    second = await tool.run(path="project:shot.png", preset="youtube_thumbnail")

    assert first.ok and second.ok
    assert first.data["path"] != second.data["path"]


def test_it_is_registered_and_asks_before_writing(project) -> None:
    """Gated by the image toggle, not confirm_writes: what it makes is a picture."""
    _root, _data, workspace = project
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)

    assert "image_edit" in registry.names()
    args = {"path": "x.png", "preset": "youtube_thumbnail"}
    assert registry.needs_confirm("image_edit", args)
    assert not registry.needs_confirm("image_edit", args, confirm_image=False)
    # And it must not be dragged along by an unrelated toggle.
    assert registry.needs_confirm("image_edit", args, confirm_writes=False)
    assert capability_class("image_edit", args) == "SIDE_EFFECT_LOCAL"


def test_it_can_be_turned_off(project) -> None:
    _root, _data, workspace = project
    registry = build_tool_registry(
        {"tools": {"image_edit": {"enabled": False}}, "agent": {}}, workspace
    )

    assert "image_edit" not in registry.names()


def test_an_unattended_job_may_still_resize(project) -> None:
    """No model, no network, nobody to ask — unlike vision, which needs a person."""
    _root, _data, workspace = project
    registry = build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, allow_send=False
    )

    assert "image_edit" in registry.names()
    assert "vision" not in registry.names()


def test_an_attachment_turn_can_see_the_tool(project) -> None:
    """The subset for an attachment ask has to contain the tool that answers it."""
    _root, _data, workspace = project
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)

    visible = filter_tool_names(
        registry.names(),
        role="fast",
        text="make this more vibrant and resize it to 1280 x 720",
        enabled=True,
        skill_subset=True,
    )

    assert "image_edit" in visible


@pytest.mark.asyncio
async def test_the_name_says_what_happened(project, tool) -> None:
    """outputs/images is browsed by eye, so the filename earns its keep."""
    root, _data, _ws = project
    _write(root / "holiday.png", (2000, 1000))

    result = await tool.run(
        path="project:holiday.png", preset="youtube_thumbnail", vibrance=1.2
    )

    assert result.ok
    name = result.data["path"].rsplit("/", 1)[-1]
    assert name.startswith("holiday-")
    assert "1280x720" in name
    assert "vibrant" in name


@pytest.mark.asyncio
async def test_centered_text_overlay_writes_a_new_file(project, tool) -> None:
    """'Add text that says Arelis' is pixel work, not a new generate."""
    root, _data, _ws = project
    source = _write(root / "library.png", (640, 480), (20, 40, 80))

    result = await tool.run(path="project:library.png", text="Arelis")

    assert result.ok, result.output
    assert "Arelis" in result.output
    assert result.data["text"] == "Arelis"
    assert result.data["text_align"] == "center"
    assert result.data["abs_path"] != str(source)
    assert "text" in Path(result.data["abs_path"]).name
    with Image.open(result.data["abs_path"]) as out:
        assert out.size == (640, 480)
        # Overlay must actually change pixels — a no-op save is a lie.
        with Image.open(source) as original:
            assert out.tobytes() != original.tobytes()


@pytest.mark.asyncio
async def test_rotate_90_swaps_the_shape(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "wide.png", (200, 100), (200, 40, 40))

    result = await tool.run(path="project:wide.png", rotate=90)

    assert result.ok, result.output
    assert result.data["result_px"] == [100, 200]
    assert "rotated" in result.output.lower()


@pytest.mark.asyncio
async def test_flip_horizontal_changes_pixels(project, tool) -> None:
    root, _data, _ws = project
    path = root / "arrow.png"
    img = Image.new("RGB", (20, 10), (0, 0, 0))
    img.putpixel((0, 0), (255, 0, 0))
    img.save(path)

    result = await tool.run(path="project:arrow.png", flip="horizontal")

    assert result.ok, result.output
    with Image.open(result.data["abs_path"]) as out:
        rgb = out.convert("RGB")
        assert rgb.getpixel((19, 0)) == (255, 0, 0)
        assert rgb.getpixel((0, 0)) == (0, 0, 0)


@pytest.mark.asyncio
async def test_grayscale_drops_the_colour(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "red.png", (32, 32), (220, 20, 20))

    result = await tool.run(path="project:red.png", grayscale=True)

    assert result.ok, result.output
    with Image.open(result.data["abs_path"]) as out:
        r, g, b = out.convert("RGB").getpixel((8, 8))
        assert r == g == b


@pytest.mark.asyncio
async def test_tiktok_preset_is_a_story_shape(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "shot.png", (1920, 1080))

    result = await tool.run(path="project:shot.png", preset="tiktok")

    assert result.ok, result.output
    assert result.data["result_px"] == [1080, 1920]


@pytest.mark.asyncio
async def test_crop_left_halves_the_width(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "wide.png", (200, 100), (10, 20, 30))

    result = await tool.run(path="project:wide.png", crop="left")

    assert result.ok, result.output
    assert result.data["result_px"] == [100, 100]
    assert "crop" in Path(result.data["abs_path"]).name


@pytest.mark.asyncio
async def test_crop_box_cuts_the_named_rectangle(project, tool) -> None:
    root, _data, _ws = project
    path = root / "grid.png"
    img = Image.new("RGB", (40, 30), (0, 0, 0))
    for x in range(5, 15):
        for y in range(5, 20):
            img.putpixel((x, y), (255, 0, 0))
    img.save(path)

    boxed = await tool.run(
        path="project:grid.png",
        crop_box={"left": 5, "top": 5, "right": 15, "bottom": 20},
    )

    assert boxed.ok, boxed.output
    assert boxed.data["result_px"] == [10, 15]
    with Image.open(boxed.data["abs_path"]) as out:
        assert out.size == (10, 15)
        assert out.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
        assert out.convert("RGB").getpixel((9, 14)) == (255, 0, 0)

    listed = await tool.run(path="project:grid.png", crop_box=[5, 5, 15, 20])
    assert listed.ok, listed.output
    assert listed.data["result_px"] == [10, 15]


@pytest.mark.asyncio
async def test_scale_2_doubles_pixels(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "tiny.png", (40, 30))

    result = await tool.run(path="project:tiny.png", scale=2)

    assert result.ok, result.output
    assert result.data["result_px"] == [80, 60]
    assert "scale2" in Path(result.data["abs_path"]).name


@pytest.mark.asyncio
async def test_pad_grows_the_canvas(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "stamp.png", (20, 10), (200, 100, 50))

    result = await tool.run(path="project:stamp.png", pad=8)

    assert result.ok, result.output
    assert result.data["result_px"] == [36, 26]
    assert "pad" in Path(result.data["abs_path"]).name
    with Image.open(result.data["abs_path"]) as out:
        px = out.getpixel((0, 0))
        assert px[0] == 0 and px[1] == 0 and px[2] == 0
        inner = out.convert("RGB").getpixel((8, 8))
        assert inner == (200, 100, 50)


@pytest.mark.asyncio
async def test_warmth_changes_pixels(project, tool) -> None:
    root, _data, _ws = project
    _write(root / "neutral.png", (16, 16), (120, 120, 120))

    result = await tool.run(path="project:neutral.png", warmth=1.0)

    assert result.ok, result.output
    assert "warm" in Path(result.data["abs_path"]).name
    with Image.open(result.data["abs_path"]) as out:
        red, _green, blue = out.convert("RGB").getpixel((8, 8))
        assert red > 120
        assert blue < 120


@pytest.mark.asyncio
async def test_pixel_edits_leave_the_original_untouched(project, tool) -> None:
    root, _data, _ws = project
    source = _write(root / "keep.png", (80, 60), (90, 40, 20))
    before = source.read_bytes()

    result = await tool.run(
        path="project:keep.png", crop="center", scale=2, pad=4, warmth=0.5
    )

    assert result.ok, result.output
    assert source.read_bytes() == before
    assert result.data["abs_path"] != str(source)
