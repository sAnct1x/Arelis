"""A label has to land on the spot that was asked for, not the corner."""

from __future__ import annotations

import pytest
from PIL import Image

from arelis.tools.image_edit import ImageEditTool
from arelis.workspace import WorkspaceRoots
from tests.test_image_edit import _write


@pytest.fixture
def project(tmp_path, monkeypatch):
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


def _ink_origin(path, bg: tuple[int, int, int]) -> tuple[int, int]:
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        width, height = rgb.size
        pixels = rgb.load()
        assert pixels is not None
        best: tuple[int, int] | None = None
        for y in range(height):
            for x in range(width):
                red, green, blue = pixels[x, y]
                if abs(red - bg[0]) + abs(green - bg[1]) + abs(blue - bg[2]) <= 40:
                    continue
                if best is None or (y, x) < (best[1], best[0]):
                    best = (x, y)
    assert best is not None, "label left no ink"
    return best


def _near(left: int, top: int, x: int, y: int) -> None:
    # Stroke and the font's side bearing sit a few pixels off the anchor.
    assert abs(left - x) <= 16, f"label left {left} is not near {x}"
    assert abs(top - y) <= 16, f"label top {top} is not near {y}"
    if x > 20:
        assert left > 10, f"label stuck near the origin at {left},{top}"


async def _label(tool, root, item: dict, size=(200, 160)):
    bg = (8, 8, 16)
    _write(root / "field.png", size, bg)
    result = await tool.run(path="project:field.png", annotate=[{"kind": "label", "text": "pillar", **item}])
    assert result.ok, result.output
    left, top = _ink_origin(result.data["abs_path"], bg)
    return left, top


@pytest.mark.asyncio
async def test_fraction_label_lands_on_the_pillar(project, tool) -> None:
    root, _data, _ws = project
    left, top = await _label(tool, root, {"x": 0.5, "y": 0.4}, size=(200, 150))
    _near(left, top, round(0.5 * 200), round(0.4 * 150))


@pytest.mark.asyncio
async def test_position_wins_when_xy_are_the_default_corner(project, tool) -> None:
    root, _data, _ws = project
    left, top = await _label(tool, root, {"x": 0, "y": 0, "position": [70, 40]})
    _near(left, top, 70, 40)


@pytest.mark.asyncio
async def test_x1_y1_is_the_label_spot(project, tool) -> None:
    root, _data, _ws = project
    left, top = await _label(tool, root, {"x1": 80, "y1": 40})
    _near(left, top, 80, 40)


@pytest.mark.asyncio
async def test_integer_pixels_still_land_on_that_spot(project, tool) -> None:
    root, _data, _ws = project
    left, top = await _label(tool, root, {"x": 70, "y": 40})
    _near(left, top, 70, 40)
