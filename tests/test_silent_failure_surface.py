"""Guards against failures that quietly turn into confident wrong behaviour.

These tests care about the diagnostic as well as the fallback. A fallback that
keeps the desktop alive but leaves no trace is exactly how a broken guard,
capability probe, or lessons file gets mistaken for a valid empty result.
"""

from __future__ import annotations

import ast
import builtins
import logging
import tokenize
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from arelis.core import lessons
from arelis.llm.ollama import OllamaProvider
from arelis.llm.router import ModelRouter
from arelis.memory.indexer import MemoryIndexer


class _RouterProvider:
    guard_host_vram = True


@pytest.mark.asyncio
async def test_a_missing_vram_probe_leaves_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    router = ModelRouter(_RouterProvider(), {"fast": "chat"})  # type: ignore[arg-type]
    real_import = builtins.__import__

    def fail_vram_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "arelis.llm.vram":
            raise ImportError("mutated VRAM module")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_vram_import)
    with caplog.at_level(logging.WARNING, logger="arelis.llm.router"):
        await router._refuse_if_host_vram_full()

    assert "Host VRAM guard could not load" in caplog.text
    assert "mutated VRAM module" in caplog.text


class _BrokenResponse:
    def raise_for_status(self) -> None:
        raise RuntimeError("show endpoint broke")


class _BrokenClient:
    async def post(self, path: str, *, json: dict[str, str]) -> _BrokenResponse:
        assert path == "/api/show"
        assert json == {"model": "vision-chat"}
        return _BrokenResponse()


@pytest.mark.asyncio
async def test_an_unknown_model_capability_is_warned_and_not_cached(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = OllamaProvider.__new__(OllamaProvider)
    provider._client = _BrokenClient()  # type: ignore[assignment]
    provider._capabilities = {}

    with caplog.at_level(logging.WARNING, logger="arelis.llm.ollama"):
        found = await provider.capabilities("vision-chat")

    assert found == frozenset()
    assert provider._capabilities == {}
    assert "vision support is unknown" in caplog.text
    assert "show endpoint broke" in caplog.text


class _RetryingEmbedProvider:
    def __init__(self) -> None:
        self.embed_calls = 0

    async def list_models(self) -> list[str]:
        return ["nomic-embed-text:latest"]

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        assert model == "nomic-embed-text"
        assert texts == ["remember this"]
        self.embed_calls += 1
        if self.embed_calls == 1:
            raise RuntimeError("temporary embed failure")
        return [[0.25, 0.75]]


class _PendingMessageStore:
    def __init__(self) -> None:
        self.writes: list[tuple[int, str, list[float]]] = []

    def unembedded_messages(self, *, limit: int) -> list[dict[str, Any]]:
        assert limit == 16
        return [] if self.writes else [{"id": 7, "content": "remember this"}]

    def upsert_embedding(self, row_id: int, model: str, vector: list[float]) -> None:
        self.writes.append((row_id, model, vector))

    def unembedded_document_chunks(self, *, limit: int) -> list[dict[str, Any]]:
        del limit
        return []

    def unembedded_mail(self, *, limit: int) -> list[dict[str, Any]]:
        del limit
        return []


@pytest.mark.asyncio
async def test_a_failed_embedding_batch_stays_pending_and_retries_next_tick(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _PendingMessageStore()
    provider = _RetryingEmbedProvider()
    indexer = MemoryIndexer(store, provider)  # type: ignore[arg-type]

    with caplog.at_level(logging.ERROR, logger="arelis.memory.indexer"):
        first = await indexer.run_batch()
    second = await indexer.run_batch()

    assert first == 0
    assert second == 1
    assert provider.embed_calls == 2
    assert store.writes == [(7, "nomic-embed-text", [0.25, 0.75])]
    assert "Embedding batch failed" in caplog.text
    assert "temporary embed failure" in caplog.text


def test_a_malformed_lessons_file_warns_before_using_only_built_ins(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "lessons.yaml"
    path.write_text("lessons: [unterminated", encoding="utf-8")
    lessons.invalidate_lessons_cache()
    try:
        with caplog.at_level(logging.WARNING, logger="arelis.core.lessons"):
            loaded = lessons.load_lessons(path)
    finally:
        lessons.invalidate_lessons_cache()

    assert loaded
    assert all(item.id != "from-file" for item in loaded)
    assert "using built-in lessons only" in caplog.text
    assert str(path) in caplog.text


_CLEAN_EXCEPTION_SCOPES = {
    Path("arelis/llm/router.py"): {"_refuse_if_host_vram_full"},
    Path("arelis/llm/ollama.py"): {"capabilities"},
    Path("arelis/memory/indexer.py"): {
        "model_available",
        "_embed_messages",
        "_embed_documents",
        "_embed_mail",
    },
    Path("arelis/core/lessons.py"): {"load_lessons"},
}
_VISIBLE_LOG_METHODS = {"warning", "exception", "error", "critical"}


def _has_visible_log(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in _VISIBLE_LOG_METHODS:
            return True
    return False


def _has_reason_comment(source: str, handler: ast.ExceptHandler) -> bool:
    comments = tokenize.generate_tokens(StringIO(source).readline)
    return any(
        token.type == tokenize.COMMENT
        and handler.lineno <= token.start[0] <= (handler.end_lineno or handler.lineno)
        and len(token.string.removeprefix("#").strip()) >= 12
        for token in comments
    )


def test_cleaned_exception_handlers_must_warn_or_explain_their_silence() -> None:
    """Make the convention incremental instead of pretending 460 sites are clean."""
    offenders: list[str] = []
    for path, function_names in _CLEAN_EXCEPTION_SCOPES.items():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in function_names
        }
        assert functions.keys() == function_names
        for function_name, function in functions.items():
            for handler in (
                node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)
            ):
                catches_exception = (
                    isinstance(handler.type, ast.Name) and handler.type.id == "Exception"
                )
                if not catches_exception:
                    continue
                if _has_visible_log(handler) or _has_reason_comment(source, handler):
                    continue
                offenders.append(f"{path}:{handler.lineno} ({function_name})")

    assert not offenders, "silent broad exception handler(s): " + ", ".join(offenders)
