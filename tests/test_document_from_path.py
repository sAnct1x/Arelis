"""document from_path must read outputs/documents even outside workspace roots."""

from __future__ import annotations

import pytest

from arelis.tools.document import DocumentTool
from arelis.workspace import WorkspaceRoots


@pytest.fixture
def drop_env(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    data = tmp_path / "data"
    outputs = data / "outputs"
    docs = outputs / "documents"
    docs.mkdir(parents=True)
    source = docs / "Conversion-Source.md"
    source.write_text("# Conversion Source\n\nconvert me 8812\n", encoding="utf-8")

    import arelis.paths as paths_mod
    import arelis.tools.document as document_mod

    monkeypatch.setattr(paths_mod, "user_data_dir", lambda: data)
    monkeypatch.setattr(paths_mod, "outputs_dir", lambda: outputs)
    monkeypatch.setattr(document_mod, "user_data_dir", lambda: data, raising=False)
    monkeypatch.setattr(document_mod, "outputs_dir", lambda: outputs)

    tool = DocumentTool(WorkspaceRoots.from_paths([str(project)]))
    return tool, source, docs, data, project


def test_from_path_accepts_relative_display_path(drop_env) -> None:
    tool, _source, _docs, _data, _project = drop_env
    body = tool._read_source("outputs/documents/Conversion-Source.md")
    assert "convert me 8812" in body


def test_from_path_accepts_absolute_drop_path(drop_env) -> None:
    tool, source, _docs, _data, _project = drop_env
    body = tool._read_source(str(source))
    assert "convert me 8812" in body


def test_from_path_rejects_outside_roots(drop_env) -> None:
    tool, _source, _docs, _data, project = drop_env
    outside = project.parent / "secret.md"
    outside.write_text("should not read\n", encoding="utf-8")
    with pytest.raises(ValueError, match="allowed root") as exc:
        tool._read_source(str(outside))
    assert "outputs/documents" in str(exc.value)


def test_from_path_rejects_traversal(drop_env) -> None:
    tool, _source, _docs, data, _project = drop_env
    escape = data.parent / "escape.md"
    escape.write_text("pwned\n", encoding="utf-8")
    with pytest.raises(ValueError, match="allowed root") as exc:
        tool._read_source("outputs/documents/../../escape.md")
    assert "outputs/documents" in str(exc.value)
