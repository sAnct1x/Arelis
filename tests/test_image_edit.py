"""The tool that was missing when someone asked for a YouTube thumbnail.

The ask was "make this more vibrant and resize it to 1280 x 720". There was no
tool that could do it, so three wrong ones were tried in turn: vision (which can
only look), image (which invented a different picture at the right size), and
finally the calculator, forced in because "1280 x 720" reads as arithmetic.
"""

from __future__ import annotations

import pytest
from PIL import Image

from arelis.tools.image_edit import ImageEditTool
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
async def test_a_size_beyond_the_tools_purpose_is_refused(tool, project) -> None:
    root, _data, _ws = project
    _write(root / "shot.png", (320, 240))

    result = await tool.run(path="project:shot.png", width=90000, height=90000)

    assert not result.ok
    assert "larger than" in result.output


@pytest.mark.asyncio
async def test_a_path_outside_every_readable_root_is_refused(tool, tmp_path) -> None:
    outside = tmp_path / "elsewhere" / "secret.png"
    _write(outside, (100, 100))

    result = await tool.run(path=str(outside), preset="youtube_thumbnail")

    assert not result.ok
    assert "outside" in result.output


def _circle(path, size=64, radius=18, centre=(32, 32)):
    """White circle on black. The cutout should keep the circle and drop the rest."""
    img = Image.new("RGB", (size, size), (0, 0, 0))
    pixels = img.load()
    cx, cy = centre
    for y in range(size):
        for x in range(size):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
                pixels[x, y] = (255, 255, 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


class _MaskSession:
    """Stand-in for u2netp: bright pixels are the subject."""

    def get_inputs(self):
        return [type("Input", (), {"name": "input"})()]

    def run(self, _names, feeds):
        batch = next(iter(feeds.values()))
        score = batch.mean(axis=1, keepdims=True)
        return [score]


class _NearestSession:
    """Stand-in for the 4x upscaler: repeat each pixel four times."""

    def get_inputs(self):
        return [type("Input", (), {"name": "image"})()]

    def run(self, _names, feeds):
        import numpy as np

        tile = feeds["image"]
        return [np.repeat(np.repeat(tile, 4, axis=2), 4, axis=3)]


