"""recall action=index chunks files now. It must not load nomic.

Roadmap 4.13. The idle indexer waits until the turn is free because
nomic-embed-text evicts qwen on a 12GB card. "I just added 40 PDFs" still
needs an answer during the turn: keyword search, via DocumentIndexer.sync_now,
never provider.embed / run_batch / flush.

Three mutants this file is here to kill:

1. index calls embed (copy-pasted from search). boom() raises and the
   call list is checked.
2. index is a no-op that returns ok=True. A new file must land in
   document_chunks; a canned "indexed 0 files" does not write one.
3. search still cannot see the newly synced file. source=docs must find
   the distinctive token without embeddings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.memory.docs import DocumentIndexer
from arelis.memory.store import MemoryStore
from arelis.tools.recall import RecallTool
from arelis.workspace import WorkspaceRoots

_TOKEN = "ZXQ_QUOKKA_7721"


def _workspace_with_note(tmp_path: Path) -> tuple[MemoryStore, WorkspaceRoots, DocumentIndexer, Path]:
    project = tmp_path / "papers"
    project.mkdir()
    note = project / "notes.txt"
    note.write_text(f"{_TOKEN} lives in the deck plans.\n", encoding="utf-8")
    store = MemoryStore(tmp_path / "memory.db")
    workspace = WorkspaceRoots.from_paths([str(project)])
    indexer = DocumentIndexer(store, workspace)
    return store, workspace, indexer, note


async def _boom_embed(model: str, texts: list[str]) -> list[list[float]]:
    del model, texts
    raise RuntimeError("nomic should stay on the bench during index")


@pytest.mark.asyncio
async def test_index_chunks_a_new_file_and_search_finds_it_without_embed(
    tmp_path: Path,
) -> None:
    store, workspace, indexer, _note = _workspace_with_note(tmp_path)
    embed_calls: list[tuple[str, list[str]]] = []

    async def boom(model: str, texts: list[str]) -> list[list[float]]:
        embed_calls.append((model, texts))
        raise RuntimeError("nomic should stay on the bench during index")

    try:
        tool = RecallTool(store, embed=boom, index_docs=indexer.sync_now)
        result = await tool.run(action="index")
        assert result.ok, result.output
        assert embed_calls == [], "index loaded the embed model"
        assert result.data.get("embedded") is False
        assert int(result.data.get("files") or 0) >= 1
        assert int(result.data.get("chunks") or 0) >= 1

        root = workspace.roots[0].name
        assert store.get_document(root, "notes.txt") is not None
        rows = store._conn.execute(
            "SELECT content FROM document_chunks"
        ).fetchall()
        assert any(_TOKEN in str(row["content"]) for row in rows)

        # Separate tool so search cannot hide an embed call behind index.
        found = await RecallTool(store).run(
            action="search", query=_TOKEN, source="docs"
        )
        assert found.ok, found.output
        assert _TOKEN in found.output
        assert found.data.get("mode") == "keyword"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_index_makes_a_pdf_keyword_searchable_without_embed(
    tmp_path: Path,
) -> None:
    """The stated ask is 'I just added 40 PDFs', not 40 markdown files.

    DocumentIndexer used to skip anything `looks_binary` flagged, which is
    every real PDF. Index must extract the text layer and leave nomic off
    the card. ALPHA is in tests/fixtures/quote.pdf.
    """
    import shutil

    project = tmp_path / "papers"
    project.mkdir()
    src = Path(__file__).parent / "fixtures" / "quote.pdf"
    shutil.copy(src, project / "homework.pdf")
    store = MemoryStore(tmp_path / "memory.db")
    workspace = WorkspaceRoots.from_paths([str(project)])
    indexer = DocumentIndexer(store, workspace)
    embed_calls: list[object] = []

    async def boom(model: str, texts: list[str]) -> list[list[float]]:
        embed_calls.append((model, texts))
        raise RuntimeError("nomic should stay on the bench during index")

    try:
        tool = RecallTool(store, embed=boom, index_docs=indexer.sync_now)
        result = await tool.run(action="index")
        assert result.ok, result.output
        assert embed_calls == []
        assert int(result.data.get("files") or 0) >= 1
        found = await RecallTool(store).run(
            action="search", query="ALPHA", source="docs"
        )
        assert found.ok, found.output
        assert "ALPHA" in found.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_a_configured_indexer_may_honestly_report_zero(
    tmp_path: Path,
) -> None:
    """0 files is success only when the indexer actually ran and found nothing."""
    project = tmp_path / "empty"
    project.mkdir()
    store = MemoryStore(tmp_path / "memory.db")
    workspace = WorkspaceRoots.from_paths([str(project)])
    indexer = DocumentIndexer(store, workspace)
    try:
        tool = RecallTool(store, index_docs=indexer.sync_now)
        result = await tool.run(action="index")
        assert result.ok, result.output
        assert result.data["files"] == 0
    finally:
        store.close()
