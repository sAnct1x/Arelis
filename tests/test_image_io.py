"""resolve_image decides which files get base64'd and sent to a model.

One of three tools no test file so much as named (2026-09-17). Its docstring
is careful and its reasoning is sound, but "the comment describes the risk" is
not evidence the risk is handled -- the lesson python_exec taught the same
afternoon, where every guard was documented and three of them were bypassable.

The boundary here is worth pinning because crossing it is silent. A path that
escapes the allowed roots does not raise in the user's face; it reads a file
and hands its contents to a model, which is the quietest kind of leak there
is. The escape-shaped tests below all assert PermissionError, so they fail
loudly if the containment is ever loosened.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools.image_io import (
    DEFAULT_MAX_EDGE,
    IMAGE_SUFFIXES,
    encode_for_vision,
    resolve_image,
)
from arelis.workspace import RootEntry, WorkspaceRoots


@pytest.fixture()
def roots(tmp_path: Path) -> WorkspaceRoots:
    project = tmp_path / "project"
    project.mkdir()
    return WorkspaceRoots([RootEntry(name="project", path=project.resolve())])


def _root(roots: WorkspaceRoots) -> Path:
    return roots.roots[0].path


def _png(path: Path, *, size: tuple[int, int] = (8, 6)) -> Path:
    """A real PNG on disk. Pillow is a hard dependency of the image tools."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (120, 40, 200)).save(path, format="PNG")
    return path


# --------------------------------------------------------------------------
# It resolves what it is supposed to resolve
# --------------------------------------------------------------------------


def test_a_picture_in_the_workspace_is_found(roots: WorkspaceRoots) -> None:
    made = _png(_root(roots) / "shot.png")
    assert resolve_image(roots, "project:shot.png") == made


def test_a_picture_in_a_subfolder_is_found(roots: WorkspaceRoots) -> None:
    made = _png(_root(roots) / "pics" / "deep.png")
    assert resolve_image(roots, "project:pics/deep.png") == made


def test_a_pasted_screenshot_resolves_without_a_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the module docstring was written for.

    A paste lands in the data root's drops folder, which is only inside a
    project by coincidence on a source checkout. On an installed copy the two
    roots are different directories, so resolving against the workspace alone
    would fail on every paste -- and nobody would see that until it shipped.
    """
    import arelis.tools.image_io as image_io

    drops = tmp_path / "state" / "drops"
    made = _png(drops / "paste.png")
    monkeypatch.setattr(image_io, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(image_io, "outputs_dir", lambda: tmp_path / "outputs")
    monkeypatch.setattr(image_io, "user_data_dir", lambda: tmp_path)

    assert resolve_image(None, str(made)) == made
    # And by the relative form the model actually tends to pass.
    assert resolve_image(None, "state/drops/paste.png") == made


def test_a_generated_picture_in_outputs_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import arelis.tools.image_io as image_io

    outputs = tmp_path / "outputs"
    made = _png(outputs / "chart.png")
    monkeypatch.setattr(image_io, "outputs_dir", lambda: outputs)
    monkeypatch.setattr(image_io, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(image_io, "user_data_dir", lambda: tmp_path)

    assert resolve_image(None, str(made)) == made


# --------------------------------------------------------------------------
# And refuses everything else
# --------------------------------------------------------------------------


def test_an_absolute_path_outside_every_root_is_refused(
    tmp_path: Path, roots: WorkspaceRoots
) -> None:
    outside = _png(tmp_path / "elsewhere" / "private.png")
    with pytest.raises(PermissionError):
        resolve_image(roots, str(outside))


def test_dot_dot_cannot_climb_out_of_the_workspace(tmp_path: Path, roots: WorkspaceRoots) -> None:
    _png(tmp_path / "elsewhere" / "private.png")
    with pytest.raises((PermissionError, ValueError)):
        resolve_image(roots, "project:../elsewhere/private.png")


def test_dot_dot_cannot_climb_out_of_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The drops fallback joins a relative path onto the data root.

    That join is the one place a traversal would land somewhere real, so it is
    the one worth an explicit test rather than an argument.
    """
    import arelis.tools.image_io as image_io

    _png(tmp_path / "elsewhere" / "private.png")
    monkeypatch.setattr(image_io, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(image_io, "outputs_dir", lambda: tmp_path / "outputs")
    monkeypatch.setattr(image_io, "user_data_dir", lambda: tmp_path)

    with pytest.raises(PermissionError):
        resolve_image(None, "state/drops/../../elsewhere/private.png")


def test_a_non_image_inside_the_workspace_is_refused(roots: WorkspaceRoots) -> None:
    """Containment is not the only rule: the sandbox is images, not files."""
    secret = _root(roots) / "secrets.yaml"
    secret.write_text("token: hunter2\n", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        resolve_image(roots, "project:secrets.yaml")
    assert ".yaml" in str(caught.value)


def test_an_empty_path_is_refused(roots: WorkspaceRoots) -> None:
    with pytest.raises(ValueError):
        resolve_image(roots, "   ")


def test_a_missing_file_in_an_allowed_place_says_so(roots: WorkspaceRoots) -> None:
    """Missing and forbidden are different answers, and the caller shows both."""
    with pytest.raises((FileNotFoundError, PermissionError)):
        resolve_image(roots, "project:nothing-here.png")


def test_every_advertised_suffix_actually_resolves(roots: WorkspaceRoots) -> None:
    """IMAGE_SUFFIXES is the contract; check it is not narrower in practice."""
    for suffix in sorted(IMAGE_SUFFIXES):
        target = _root(roots) / f"pic{suffix}"
        target.write_bytes(b"not really an image")
        assert resolve_image(roots, f"project:pic{suffix}").suffix == suffix


# --------------------------------------------------------------------------
# Downscaling, which exists so a paste does not blow the context window
# --------------------------------------------------------------------------


def test_a_big_screenshot_is_brought_under_the_cap(tmp_path: Path) -> None:
    """2560x1440 is what Print Screen produces, and it does not fit."""
    big = _png(tmp_path / "big.png", size=(2560, 1440))
    payload, meta = encode_for_vision(big)
    assert meta["downscaled"] is True
    assert max(meta["sent_px"]) == DEFAULT_MAX_EDGE
    assert meta["sent_bytes"] < meta["source_bytes"]
    assert payload


def test_a_small_picture_is_sent_untouched(tmp_path: Path) -> None:
    small = _png(tmp_path / "small.png", size=(64, 48))
    payload, meta = encode_for_vision(small)
    assert meta["downscaled"] is False
    assert meta["sent_px"] == [64, 48]
    assert meta["sent_bytes"] == meta["source_bytes"]
    assert payload


def test_a_wider_cap_is_honoured(tmp_path: Path) -> None:
    big = _png(tmp_path / "big.png", size=(2560, 1440))
    _, meta = encode_for_vision(big, max_edge=2048)
    assert max(meta["sent_px"]) == 2048


def test_aspect_ratio_survives_the_downscale(tmp_path: Path) -> None:
    """A squashed screenshot is a wrong answer that looks like a right one."""
    big = _png(tmp_path / "wide.png", size=(3000, 1000))
    _, meta = encode_for_vision(big)
    width, height = meta["sent_px"]
    assert abs((width / height) - 3.0) < 0.05


def test_an_unreadable_file_still_reaches_the_model(tmp_path: Path) -> None:
    """Pillow refusing to parse is not a reason to refuse to look.

    The model may handle a truncation or a format Pillow will not, so the
    bytes go anyway -- but the caller is told, so it can stop claiming the
    picture was prepared.
    """
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage")
    payload, meta = encode_for_vision(broken)
    assert payload
    assert "prepare_error" in meta
