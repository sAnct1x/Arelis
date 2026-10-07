"""Background embedding of archived messages, docs, and (opt-in) mail.

Runs between turns, never during one. Loading nomic-embed-text while qwen is
answering would evict the chat model on a 12GB card; the indexer waits until
the UI says the turn is idle, then syncs a few files / peeks mail, embeds a
small batch, and unloads.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from arelis.llm.ollama import OllamaProvider
from arelis.mail import MailAccount
from arelis.memory.docs import (
    DEFAULT_CHUNK_CHARS,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_MAX_FILE_BYTES,
    DocumentIndexer,
)
from arelis.memory.mail_index import (
    DEFAULT_MAX_BODY_CHARS,
    DEFAULT_MAX_MESSAGES,
    DEFAULT_MIN_INTERVAL_S,
    DEFAULT_RETENTION_DAYS,
    MailIndexer,
)
from arelis.memory.store import MemoryStore
from arelis.workspace import WorkspaceRoots

log = logging.getLogger(__name__)

DEFAULT_EMBED_MODEL = "nomic-embed-text"
_BATCH = 16
_DOC_FILES_PER_TICK = 4

EmbedFn = Callable[[str, list[str]], Awaitable[list[list[float]]]]


class MemoryIndexer:
    """Fill embeddings for messages, document chunks, and mail that lack them."""

    def __init__(
        self,
        store: MemoryStore,
        provider: OllamaProvider,
        *,
        model: str = DEFAULT_EMBED_MODEL,
        batch_size: int = _BATCH,
        workspace: WorkspaceRoots | None = None,
        docs: DocumentIndexer | None = None,
        index_docs: bool = True,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        chunk_chars: int = DEFAULT_CHUNK_CHARS,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        mail: MailIndexer | None = None,
        index_mail: bool = False,
        mail_account: MailAccount | None = None,
        mail_host: str = "imap.gmail.com",
        mail_port: int = 993,
        mail_timeout_s: float = 30.0,
        mail_max_messages: int = DEFAULT_MAX_MESSAGES,
        mail_retention_days: int = DEFAULT_RETENTION_DAYS,
        mail_max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
        mail_min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
    ) -> None:
        self.store = store
        self.provider = provider
        self.model = model
        self.batch_size = batch_size
        self._available: bool | None = None
        self.docs: DocumentIndexer | None
        self.mail: MailIndexer | None
        if docs is not None:
            self.docs = docs
        elif index_docs and workspace is not None:
            self.docs = DocumentIndexer(
                store,
                workspace,
                max_file_bytes=max_file_bytes,
                chunk_chars=chunk_chars,
                chunk_overlap=chunk_overlap,
            )
        else:
            self.docs = None

        if mail is not None:
            self.mail = mail
        elif index_mail and mail_account is not None:
            self.mail = MailIndexer(
                store,
                mail_account,
                host=mail_host,
                port=mail_port,
                timeout_s=mail_timeout_s,
                max_messages=mail_max_messages,
                retention_days=mail_retention_days,
                max_body_chars=mail_max_body_chars,
                min_interval_s=mail_min_interval_s,
            )
        else:
            self.mail = None

    async def model_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            names = await self.provider.list_models()
        except Exception:
            log.exception("Could not list Ollama models for embed availability")
            self._available = False
            return False
        # Tags may be "nomic-embed-text" or "nomic-embed-text:latest".
        self._available = any(
            name == self.model or name.startswith(f"{self.model}:") for name in names
        )
        return self._available

    async def run_batch(self) -> int:
        """Sync docs/mail if needed, then embed one batch of pending rows."""
        synced = 0
        if self.docs is not None:
            synced += await asyncio.to_thread(
                self.docs.sync_batch, max_files=_DOC_FILES_PER_TICK
            )
        if self.mail is not None:
            synced += await asyncio.to_thread(self.mail.sync_batch)

        if not await self.model_available():
            return synced

        # Prefer draining chat backlog first so conversation recall stays warm.
        written = await self._embed_messages()
        if written == 0:
            written = await self._embed_documents()
        if written == 0:
            written = await self._embed_mail()
        return synced + written

    async def _embed_messages(self) -> int:
        rows = self.store.unembedded_messages(limit=self.batch_size)
        if not rows:
            return 0
        texts = [str(row["content"]) for row in rows]
        try:
            vectors = await self.provider.embed(self.model, texts)
        except Exception:
            log.exception("Embedding batch failed")
            return 0
        written = 0
        for row, vector in zip(rows, vectors, strict=True):
            self.store.upsert_embedding(int(row["id"]), self.model, vector)
            written += 1
        if written:
            log.info("Embedded %d archived message(s) with %s", written, self.model)
        return written

    async def _embed_documents(self) -> int:
        rows = self.store.unembedded_document_chunks(limit=self.batch_size)
        if not rows:
            return 0
        texts = [str(row["content"]) for row in rows]
        try:
            vectors = await self.provider.embed(self.model, texts)
        except Exception:
            log.exception("Document embedding batch failed")
            return 0
        written = 0
        for row, vector in zip(rows, vectors, strict=True):
            self.store.upsert_document_embedding(int(row["id"]), self.model, vector)
            written += 1
        if written:
            log.info("Embedded %d document chunk(s) with %s", written, self.model)
        return written

    async def _embed_mail(self) -> int:
        rows = self.store.unembedded_mail(limit=self.batch_size)
        if not rows:
            return 0
        texts = [str(row["content"]) for row in rows]
        try:
            vectors = await self.provider.embed(self.model, texts)
        except Exception:
            log.exception("Mail embedding batch failed")
            return 0
        written = 0
        for row, vector in zip(rows, vectors, strict=True):
            self.store.upsert_mail_embedding(int(row["id"]), self.model, vector)
            written += 1
        if written:
            log.info("Embedded %d mail message(s) with %s", written, self.model)
        return written

    async def flush(self, *, max_batches: int = 50) -> int:
        """Drain file/mail sync and embedding backlog at shutdown."""
        total = 0
        if self.docs is not None:
            for _ in range(max_batches):
                n = await asyncio.to_thread(self.docs.sync_batch, max_files=32)
                total += n
                if n == 0:
                    break
        if self.mail is not None:
            total += await asyncio.to_thread(self.mail.sync_batch, force=True)
        for _ in range(max_batches):
            if not await self.model_available():
                break
            n = await self._embed_messages()
            if n == 0:
                n = await self._embed_documents()
            if n == 0:
                n = await self._embed_mail()
            if n == 0:
                break
            total += n
        return total
