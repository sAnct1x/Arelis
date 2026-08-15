"""Workspace files are chunked into memory and searchable via recall."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.memory.docs import DocumentIndexer, chunk_text, looks_binary
from arelis.memory.store import MemoryStore
from arelis.tools.recall import RecallTool
from arelis.workspace import WorkspaceRoots


def test_chunk_text_splits_long_files_with_overlap() -> None:
    text = ("paragraph one about mirrors.\n\n" * 40) + "tail marker unique"
    chunks = chunk_text(text, chunk_chars=200, overlap=40)
    assert len(chunks) > 1
    assert any("tail marker unique" in c for c in chunks)


def test_null_bytes_mean_binary() -> None:
    assert looks_binary(b"hello\x00world")
    assert not looks_binary(b"hello world\n")


def test_document_indexer_writes_chunks_and_skips_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    note = root / "notes.md"
    note.write_text(
        "We aligned the interferometer mirrors carefully.\n", encoding="utf-8"
    )
    (root / "skip.bin").write_bytes(b"\x00\x01\x02\x03binary")

    store = MemoryStore(tmp_path / "memory.db")
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(root)]}})
    indexer = DocumentIndexer(store, workspace)

    assert indexer.sync_batch(max_files=10) == 1
    assert indexer.sync_batch(max_files=10) == 0
    hits = store.search_documents("interferometer")
    assert hits
    assert hits[0].source == "doc"
    assert "interferometer" in hits[0].content.lower()
    assert "notes.md" in hits[0].path
    store.close()


def test_deleted_files_are_pruned_from_the_archive(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    path = root / "gone.md"
    path.write_text("temporary secret phrase xyzzy", encoding="utf-8")
    store = MemoryStore(tmp_path / "memory.db")
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(root)]}})
    indexer = DocumentIndexer(store, workspace)
    assert indexer.sync_batch() == 1
    path.unlink()
    indexer.sync_batch()
    assert store.search_documents("xyzzy") == []
    store.close()


@pytest.mark.asyncio
async def test_recall_can_search_docs_only(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "readme.md").write_text(
        "Calibration checklist for the lab telescope.\n", encoding="utf-8"
    )
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    from arelis.core.memory import SessionMemory

    memory = SessionMemory(sink=store)
    memory.add("user", "I bought groceries.")

    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(root)]}})
    DocumentIndexer(store, workspace).sync_batch()

    tool = RecallTool(store)
    docs = await tool.run(action="search", query="telescope", source="docs")
    assert docs.ok
    assert "telescope" in docs.output.lower()
    assert "file=" in docs.output

    chat = await tool.run(action="search", query="groceries", source="chat")
    assert chat.ok
    assert "groceries" in chat.output.lower()

    miss = await tool.run(action="search", query="groceries", source="docs")
    assert miss.ok
    assert "No indexed files matched" in miss.output
    store.close()
