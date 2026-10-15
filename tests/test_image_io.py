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


# --------------------------------------------------------------------------
# And refuses everything else
# --------------------------------------------------------------------------


def test_an_absolute_path_outside_every_root_is_refused(
    tmp_path: Path, roots: WorkspaceRoots
) -> None:
    outside = _png(tmp_path / "elsewhere" / "private.png")
    with pytest.raises(PermissionError):
        resolve_image(roots, str(outside))


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


# --------------------------------------------------------------------------
# Downscaling, which exists so a paste does not blow the context window
# --------------------------------------------------------------------------


