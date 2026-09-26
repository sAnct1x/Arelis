"""action=docs is first-class local file search. Same index as source=docs.

Roadmap 5.3. The embedding/keyword index already exists. A 9B should not
have to know the source=docs trick to search PDFs. action=docs forces
that source, optional kind=pdf/docx/md drops the wrong suffix, and a miss
stays a miss.

Three mutants this file is here to kill:

1. action=docs that still searches chat. A token in an archived message
   must not appear as a session hit.
2. kind=pdf that returns a .md hit. Same token in notes.md and paper.pdf;
   kind=pdf may only return the pdf.
3. empty query is ok=True (or silently searches everything). docs needs a
   query, same as search.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.memory import SessionMemory
from arelis.memory.store import MemoryStore
from arelis.tools.recall import RecallTool

_TOKEN = "ZXQ_DOCS_5519"


def _index_file(store: MemoryStore, rel_path: str, text: str) -> None:
    store.replace_document_chunks(
        root_name="papers",
        rel_path=rel_path,
        mtime_ns=1,
        size=len(text),
        chunks=[text],
    )


def test_docs_is_a_first_class_action() -> None:
    props = RecallTool.parameters_schema["properties"]
    assert "docs" in props["action"]["enum"]
    assert props["kind"]["enum"] == ["pdf", "docx", "md"]


@pytest.mark.asyncio
async def test_action_docs_does_not_search_chat(tmp_path: Path) -> None:
    """The mutant that forgets to force source=docs fails here."""
    store = MemoryStore(tmp_path / "memory.db")
    try:
        store.start_session()
        SessionMemory(sink=store).add(
            "user", f"{_TOKEN} was only in last night's chat."
        )
        _index_file(store, "deck.pdf", f"{_TOKEN} lives in the deck plans.")

        leaked = await RecallTool(store).run(action="search", query=_TOKEN)
        assert leaked.ok, leaked.output
        assert any(hit["source"] == "chat" for hit in leaked.data["hits"])

        found = await RecallTool(store).run(
            action="docs", query=_TOKEN, source="chat"
        )
        assert found.ok, found.output
        assert found.data.get("source") == "docs"
        assert found.data.get("mode") == "keyword"
        hits = found.data["hits"]
        assert hits, found.output
        assert all(hit["source"] == "doc" for hit in hits)
        assert all(
            str(hit.get("path") or "").endswith(".pdf") for hit in hits
        )
        assert "session=" not in found.output
        assert _TOKEN in found.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_kind_pdf_does_not_return_a_markdown_hit(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    try:
        _index_file(store, "notes.md", f"{_TOKEN} is in the markdown notes.")
        _index_file(store, "paper.pdf", f"{_TOKEN} is in the homework pdf.")

        both = await RecallTool(store).run(action="docs", query=_TOKEN)
        assert both.ok, both.output
        paths = [str(hit.get("path") or "") for hit in both.data["hits"]]
        assert any(path.endswith(".md") for path in paths), paths
        assert any(path.endswith(".pdf") for path in paths), paths

        pdf = await RecallTool(store).run(
            action="docs", query=_TOKEN, kind="pdf"
        )
        assert pdf.ok, pdf.output
        assert pdf.data.get("kind") == "pdf"
        pdf_paths = [str(hit.get("path") or "") for hit in pdf.data["hits"]]
        assert pdf_paths, pdf.output
        assert all(path.endswith(".pdf") for path in pdf_paths), pdf_paths
        assert not any(path.endswith(".md") for path in pdf_paths), pdf_paths
        assert "notes.md" not in pdf.output
        assert "paper.pdf" in pdf.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_kind_pdf_against_only_markdown_is_a_miss(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    try:
        _index_file(store, "notes.md", f"{_TOKEN} is only in markdown.")
        result = await RecallTool(store).run(
            action="docs", query=_TOKEN, kind="pdf"
        )
        assert result.ok, result.output
        assert result.data["hits"] == []
        assert "miss" in result.output.lower()
        assert "invent" in result.output.lower()
        assert "notes.md" not in result.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_empty_docs_query_fails(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    try:
        tool = RecallTool(store)
        blank = await tool.run(action="docs")
        assert blank.ok is False
        assert "query" in blank.output.lower()

        spaces = await tool.run(action="docs", query="   ")
        assert spaces.ok is False
        assert "query" in spaces.output.lower()
    finally:
        store.close()


@pytest.mark.asyncio
async def test_docs_miss_says_it_is_a_miss(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    try:
        _index_file(store, "other.pdf", "unrelated homework text")
        result = await RecallTool(store).run(
            action="docs", query="NO_SUCH_TOKEN_zzq"
        )
        assert result.ok is True
        assert result.data["hits"] == []
        assert "miss" in result.output.lower()
        assert "invent" in result.output.lower()
        assert "unrelated homework" not in result.output
    finally:
        store.close()
