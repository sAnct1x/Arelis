"""Download / upload / tab PDF — outputs jail, type=file refused."""

from __future__ import annotations

import asyncio

from arelis.browser.files import resolve_upload_path
from arelis.browser.session import BrowserSession
from arelis.tools.browser_tool import BrowserTool
from arelis.workspace import WorkspaceRoots


def test_resolve_upload_allows_outputs_only(tmp_path, monkeypatch) -> None:
    out = tmp_path / "outputs"
    out.mkdir()
    allowed = out / "note.txt"
    allowed.write_text("hi", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("no", encoding="utf-8")
    monkeypatch.setattr("arelis.browser.files.outputs_dir", lambda: out)
    hit, err = resolve_upload_path(str(allowed))
    assert hit == allowed.resolve()
    assert not err
    miss, err = resolve_upload_path(str(outside))
    assert miss is None
    assert "outputs" in err.lower() or "roots" in err.lower()


def test_resolve_upload_allows_workspace_root(tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "resume.pdf"
    src.write_bytes(b"%PDF")
    workspace = WorkspaceRoots.from_paths([str(root)])
    hit, err = resolve_upload_path(str(src), workspace=workspace)
    assert hit is not None
    assert not err
    assert hit.name == "resume.pdf"


def test_type_file_is_refused() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://example.com")
        result = await tool.run(action="type", ref="e10", text="C:\\\\x.pdf")
        assert not result.ok
        assert result.data.get("code") == "FILE_INPUT"
        assert "upload" in result.output.lower()

    asyncio.run(_run())


def test_download_and_pdf_land_under_outputs(tmp_path, monkeypatch) -> None:
    out = tmp_path / "outputs"
    out.mkdir()
    monkeypatch.setattr("arelis.browser.files.outputs_dir", lambda: out)
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://example.com")
        down = await tool.run(action="download", ref="e12")
        assert down.ok
        assert down.data.get("file_ready") is True
        dest = out / "downloads"
        assert dest.is_dir()
        assert list(dest.iterdir())
        pdf = await tool.run(action="pdf")
        assert pdf.ok
        assert pdf.data.get("file_ready") is True
        docs = out / "documents"
        assert any(p.suffix == ".pdf" for p in docs.iterdir())

    asyncio.run(_run())


def test_upload_from_outputs(tmp_path, monkeypatch) -> None:
    out = tmp_path / "outputs"
    out.mkdir()
    src = out / "cv.pdf"
    src.write_bytes(b"%PDF")
    monkeypatch.setattr("arelis.browser.files.outputs_dir", lambda: out)
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="https://example.com")
        result = await tool.run(action="upload", ref="e10", path=str(src))
        assert result.ok
        assert session._driver.uploaded[-1] == ("e10", str(src.resolve()))  # type: ignore[attr-defined]

    asyncio.run(_run())
