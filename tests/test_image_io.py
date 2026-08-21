"""Where a picture may be read from, and how big it is when it reaches a model.

The bug behind this file: pasting a 1440p screenshot and asking what was in it
always failed. Ollama counts the image against the same context window as the
text, and the full-size file came to ~4,150 tokens against a 4,096 window, so it
was rejected with a 400 before the model looked at anything.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from arelis.tools.image_io import (
    DEFAULT_MAX_EDGE,
    encode_for_vision,
    resolve_image,
)
from arelis.workspace import WorkspaceRoots


@pytest.fixture
def split_layout(tmp_path, monkeypatch):
    """Data root and workspace root in different places, as an install has."""
    project = tmp_path / "Documents" / "Arelis"
    project.mkdir(parents=True)
    data = tmp_path / "LocalAppData" / "Arelis"
    (data / "data" / "drops" / "20260817").mkdir(parents=True)
    (data / "outputs" / "images").mkdir(parents=True)
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "project", "path": str(project)}]}}
    )
    return project, data, workspace


def _png(path, size=(64, 48)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 120, 200)).save(path)
    return path


def test_a_staged_paste_resolves_when_the_data_root_is_not_the_workspace(split_layout):
    _project, data, workspace = split_layout
    _png(data / "data" / "drops" / "20260817" / "paste.png")

    found = resolve_image(workspace, "data/drops/20260817/paste.png")

    assert found == (data / "data" / "drops" / "20260817" / "paste.png").resolve()


def test_a_generated_image_resolves_the_same_way(split_layout):
    _project, data, workspace = split_layout
    _png(data / "outputs" / "images" / "made.png")

    found = resolve_image(workspace, "outputs/images/made.png")

    assert found == (data / "outputs" / "images" / "made.png").resolve()


def test_a_project_file_still_wins(split_layout):
    project, _data, workspace = split_layout
    _png(project / "shot.png")

    assert resolve_image(workspace, "project:shot.png") == (project / "shot.png").resolve()


def test_somewhere_else_entirely_is_refused(split_layout, tmp_path):
    _project, _data, workspace = split_layout
    outside = _png(tmp_path / "elsewhere" / "private.png")

    with pytest.raises(PermissionError):
        resolve_image(workspace, str(outside))


def test_a_missing_file_in_an_allowed_place_says_it_is_missing(split_layout):
    _project, _data, workspace = split_layout

    with pytest.raises(FileNotFoundError):
        resolve_image(workspace, "outputs/images/never-made.png")


def test_a_non_image_is_named_as_the_wrong_type(split_layout):
    project, _data, workspace = split_layout
    (project / "notes.md").write_text("words", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported image type"):
        resolve_image(workspace, "project:notes.md")


def test_an_empty_path_is_refused(split_layout):
    _project, _data, workspace = split_layout

    with pytest.raises(ValueError, match="Missing path"):
        resolve_image(workspace, "   ")


def test_a_screenshot_is_downscaled_to_fit_the_context(tmp_path):
    """The whole point: 2560x1440 does not fit, 1024 on the long edge does."""
    source = _png(tmp_path / "big.png", (2560, 1440))

    b64, meta = encode_for_vision(source)

    # The payload, not just the bookkeeping: this is the number that used to
    # overflow the context window.
    assert len(base64.b64decode(b64)) == meta["sent_bytes"]
    assert meta["downscaled"] is True
    assert meta["source_px"] == [2560, 1440]
    assert max(meta["sent_px"]) == DEFAULT_MAX_EDGE
    assert meta["sent_px"] == [1024, 576]
    assert meta["sent_bytes"] < meta["source_bytes"]


def test_a_chat_look_can_take_a_longer_edge(tmp_path):
    """2048 is for the chat window. 1024 stays the 3B default."""
    from arelis.tools.image_io import CHAT_MAX_EDGE

    source = _png(tmp_path / "big.png", (2560, 1440))

    _b64, meta = encode_for_vision(source, max_edge=CHAT_MAX_EDGE)

    assert meta["downscaled"] is True
    assert meta["sent_px"] == [2048, 1152]


def test_the_shape_survives_the_downscale(tmp_path):
    source = _png(tmp_path / "tall.png", (600, 1800))

    _b64, meta = encode_for_vision(source, max_edge=900)

    assert meta["sent_px"] == [300, 900]


def test_a_small_image_is_sent_exactly_as_it_is(tmp_path):
    """Re-encoding a thumbnail would cost quality for no benefit."""
    source = _png(tmp_path / "small.png", (400, 300))

    b64, meta = encode_for_vision(source)

    assert meta["downscaled"] is False
    assert base64.b64decode(b64) == source.read_bytes()


def test_what_was_sent_is_decodable_at_the_size_reported(tmp_path):
    source = _png(tmp_path / "big.png", (3000, 2000))

    b64, meta = encode_for_vision(source)

    with Image.open(io.BytesIO(base64.b64decode(b64))) as sent:
        assert list(sent.size) == meta["sent_px"]


def test_a_file_pillow_cannot_parse_is_still_offered_to_the_model(tmp_path):
    """A format Pillow refuses may still be one the model handles."""
    broken = tmp_path / "truncated.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage")

    b64, meta = encode_for_vision(broken)

    assert "prepare_error" in meta
    assert base64.b64decode(b64) == broken.read_bytes()
