"""Search past conversations and indexed workspace files.

Recall is a search, not recollection. Results carry their dates so the model
can say "you told me this in March" rather than asserting it timelessly, and a
miss is reported as a miss rather than invented.

When embeddings exist, keyword and vector hits are merged by reciprocal rank.
Query embedding can briefly load nomic-embed-text; keep_alive is 0 so it does
not stay resident. If that model is not pulled, search stays keyword-only and
says so once.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from arelis.memory.rrf import merge_ranked_hits
from arelis.memory.store import MemoryStore, SearchHit
from arelis.tools.base import ToolResult

_EXCERPT_CHARS = 300
_DEFAULT_LIMIT = 8
_MAX_LIMIT = 20
_SESSION_MESSAGE_CAP = 40

EmbedFn = Callable[[str, list[str]], Awaitable[list[list[float]]]]
ModelCheckFn = Callable[[], Awaitable[bool]]
# int = files; (files, chunks) when the indexer reports both.
IndexFn = Callable[..., Awaitable[int | tuple[int, int]] | int | tuple[int, int]]


class RecallTool:
    name = "recall"
    description = (
        "Search past conversations, indexed project files, and (when enabled) "
        "peeked mail, or read one conversation back. Use this before claiming "
        "you do not know something the user may have said, written, or received. "
        "Results are dated excerpts, not perfect memory. Pass source=docs, "
        "source=chat, or source=mail to narrow; source=all (default) searches "
        "everything that is indexed. action=index chunks new files for "
        "keyword search now; embeddings wait until the turn is idle."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "session", "index"],
                "description": (
                    "search finds chat, file, and/or mail excerpts by keyword; "
                    "session reads one conversation back by id; "
                    "index chunks newly added workspace files (and peeked "
                    "mail) for keyword search without loading the embed model"
                ),
            },
            "query": {
                "type": "string",
                "description": "Keywords to search for, for action=search",
            },
            "source": {
                "type": "string",
                "enum": ["all", "chat", "docs", "mail"],
                "description": (
                    "Where to search: all (default), chat, indexed files, or "
                    "indexed mail (mail requires memory.mail.enabled)"
                ),
            },
            "session_id": {
                "type": "string",
                "description": "Session id from a chat search hit, for action=session",
            },
            "limit": {
                "type": "integer",
                "description": (
                    "How many search hits or session messages to return "
                    f"(default {_DEFAULT_LIMIT} for search, {_SESSION_MESSAGE_CAP} "
                    f"for session; max {_MAX_LIMIT})"
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Skip this many ranked hits (or session messages from the "
                    "oldest end of the shown window) before returning. Default 0. "
                    "Takes precedence over page when both are set."
                ),
            },
            "page": {
                "type": "integer",
                "description": (
                    "1-based page index for search/session paging. Equivalent to "
                    "offset=(page-1)*limit when offset is omitted."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Optional folder or file, for action=index. Limits docs "
                    "to that workspace path."
                ),
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        store: MemoryStore,
        *,
        embed: EmbedFn | None = None,
        embed_model: str = "nomic-embed-text",
        embed_available: ModelCheckFn | None = None,
        index_docs: IndexFn | None = None,
        index_mail: IndexFn | None = None,
    ) -> None:
        self.store = store
        self._embed = embed
        self._embed_model = embed_model
        self._embed_available = embed_available
        self._index_docs = index_docs
        self._index_mail = index_mail
        self._said_keyword_only = False

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        # Query without action is search. The 9B often omits the enum and
        # used to get "Unknown action ''" for a perfectly good lookup.
        if not action and str(kwargs.get("query") or "").strip():
            action = "search"
        if action == "search":
            return await self._search(kwargs)
        if action == "session":
            return self._session(kwargs)
        if action == "index":
            return await self._index(kwargs)
        return ToolResult(
            ok=False,
            output=f"Unknown action {action!r}. Use search, session, or index.",
        )

    async def _search(self, kwargs: dict[str, Any]) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, output="search needs a query.")
        source = str(kwargs.get("source") or "all").strip().lower()
        if source not in {"all", "chat", "docs", "mail"}:
            return ToolResult(
                ok=False,
                output="source must be all, chat, docs, or mail.",
            )
        limit = _clamp_limit(kwargs.get("limit"), _DEFAULT_LIMIT)
        offset = _resolve_offset(kwargs, limit=limit)
        fetch_limit = min(_MAX_LIMIT, limit + offset)

        fts_hits: list[SearchHit] = []
        if source in {"all", "chat"}:
            fts_hits.extend(self.store.search(query, limit=fetch_limit))
        if source in {"all", "docs"}:
            fts_hits.extend(self.store.search_documents(query, limit=fetch_limit))
        if source in {"all", "mail"}:
            fts_hits.extend(self.store.search_mail(query, limit=fetch_limit))

        vector_hits: list[SearchHit] = []
        mode = "keyword"
        note = ""

        if self._embed is not None:
            available = True
            if self._embed_available is not None:
                available = await self._embed_available()
            if not available:
                if not self._said_keyword_only:
                    note = (
                        " Semantic search is off until `ollama pull "
                        f"{self._embed_model}` completes; using keywords only."
                    )
                    self._said_keyword_only = True
            else:
                try:
                    vectors = await self._embed(self._embed_model, [query])
                    if vectors:
                        if source in {"all", "chat"}:
                            vector_hits.extend(
                                self.store.vector_search(
                                    vectors[0],
                                    model=self._embed_model,
                                    limit=fetch_limit,
                                )
                            )
                        if source in {"all", "docs"}:
                            vector_hits.extend(
                                self.store.vector_search_documents(
                                    vectors[0],
                                    model=self._embed_model,
                                    limit=fetch_limit,
                                )
                            )
                        if source in {"all", "mail"}:
                            vector_hits.extend(
                                self.store.vector_search_mail(
                                    vectors[0],
                                    model=self._embed_model,
                                    limit=fetch_limit,
                                )
                            )
                        mode = "hybrid" if fts_hits else "semantic"
                except Exception as exc:
                    note = f" Semantic search failed ({exc}); using keywords only."

        ranked = merge_ranked_hits(fts_hits, vector_hits, limit=fetch_limit)
        hits = ranked[offset : offset + limit]
        where = {
            "all": "past messages, files, or mail",
            "chat": "past messages",
            "docs": "indexed files",
            "mail": "indexed mail",
        }[source]
        if not hits:
            return ToolResult(
                ok=True,
                output=(
                    f"No {where} matched {query!r}. That is a search miss, "
                    "not proof the user never said or wrote it - ask them rather "
                    "than inventing."
                    + note
                ),
                data={
                    "hits": [],
                    "fts": self.store.fts_available,
                    "mode": mode,
                    "source": source,
                    "limit": limit,
                    "offset": offset,
                },
            )

        label = {
            "hybrid": "keyword + semantic",
            "semantic": "semantic",
            "keyword": "full-text" if self.store.fts_available else "substring",
        }[mode]
        lines = [f"Found {len(hits)} match(es) for {query!r} in {source} ({label}):"]
        if note:
            lines[0] = lines[0] + note
        payload: list[dict[str, Any]] = []
        for hit in hits:
            lines.append(_format_hit(hit))
            payload.append(
                {
                    "message_id": hit.message_id,
                    "session_id": hit.session_id,
                    "role": hit.role,
                    "created_at": hit.created_at,
                    "title": hit.title,
                    "excerpt": _excerpt(hit.content),
                    "source": hit.source,
                    "path": hit.path,
                    "chunk_id": hit.chunk_id,
                }
            )
        if any(h.source == "chat" for h in hits):
            lines.append(
                "Use action=session with a session_id above to read that conversation back."
            )
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={
                "hits": payload,
                "mode": mode,
                "fts": self.store.fts_available,
                "source": source,
                "limit": limit,
                "offset": offset,
            },
        )

    def _session(self, kwargs: dict[str, Any]) -> ToolResult:
        session_id = str(kwargs.get("session_id") or "").strip()
        if not session_id:
            return ToolResult(
                ok=False,
                output="session needs a session_id from a search hit.",
            )
        messages = [
            m
            for m in self.store.get_messages(session_id)
            if str(m.get("role") or "") != "notice"
        ]
        if not messages:
            return ToolResult(
                ok=False,
                output=f"No conversation with session_id {session_id!r}.",
            )
        limit = _clamp_limit(kwargs.get("limit"), _SESSION_MESSAGE_CAP)
        offset = _resolve_offset(kwargs, limit=limit)
        # Newest-first window with optional skip: offset=0 is the latest page.
        end = len(messages) - offset
        if end <= 0:
            slice_: list[dict[str, Any]] = []
        else:
            start = max(0, end - limit)
            slice_ = messages[start:end]
        summary = self.store.get_summary(session_id)
        session = self.store.get_session(session_id)
        title = str((session or {}).get("title") or "")
        header = f"Session {session_id}"
        if title:
            header += f" - {title}"
        lines = [header]
        if summary:
            lines.append(f"[earlier summary: {summary}]")
        if slice_:
            lines.append(
                f"(showing {len(slice_)} of {len(messages)} messages; "
                f"offset={offset}, limit={limit})"
            )
        elif messages:
            lines.append(
                f"(no messages in this page; {len(messages)} total, "
                f"offset={offset}, limit={limit})"
            )
        for message in slice_:
            when = _format_when(str(message.get("created_at") or ""))
            role = str(message.get("role") or "?")
            content = _excerpt(str(message.get("content") or ""), limit=500)
            lines.append(f"[{when}] {role}: {content}")
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={
                "session_id": session_id,
                "title": title,
                "message_count": len(messages),
                "shown": len(slice_),
                "limit": limit,
                "offset": offset,
            },
        )

    async def _index(self, kwargs: dict[str, Any]) -> ToolResult:
        """Chunk docs / peek mail. Does not load nomic-embed-text."""
        source = str(kwargs.get("source") or "all").strip().lower()
        if source not in {"all", "docs", "mail"}:
            return ToolResult(
                ok=False,
                output="index source must be all, docs, or mail (not chat).",
            )
        path = str(kwargs.get("path") or "").strip() or None

        want_docs = source in {"all", "docs"}
        want_mail = source in {"all", "mail"}
        if want_docs and self._index_docs is None and (
            source == "docs" or self._index_mail is None
        ):
            return ToolResult(
                ok=False,
                output=(
                    "No document indexer is configured. Files cannot be made "
                    "searchable until a workspace indexer is wired."
                ),
            )
        if want_mail and source == "mail" and self._index_mail is None:
            return ToolResult(
                ok=False,
                output="Mail indexing is not enabled.",
            )
        if not want_docs and not want_mail:
            return ToolResult(
                ok=False,
                output="index needs source=docs, source=mail, or source=all.",
            )

        files = 0
        chunks: int | None = None
        mail = 0
        if want_docs and self._index_docs is not None:
            try:
                files, chunks = await _call_index(self._index_docs, path)
            except Exception as exc:
                return ToolResult(
                    ok=False,
                    output=f"Document index failed: {exc}",
                )
        if want_mail and self._index_mail is not None:
            try:
                mail, _mail_chunks = await _call_index(self._index_mail, None)
            except Exception as exc:
                return ToolResult(
                    ok=False,
                    output=f"Mail index failed: {exc}",
                )

        parts: list[str] = []
        if want_docs and self._index_docs is not None:
            if chunks is not None:
                parts.append(f"{files} file(s), {chunks} chunk(s)")
            else:
                parts.append(f"{files} file(s)")
        if want_mail and self._index_mail is not None:
            parts.append(f"{mail} mail message(s)")
        what = " and ".join(parts) if parts else "nothing"
        if files == 0 and mail == 0:
            lines = [f"Indexed {what} (already up to date)."]
        else:
            lines = [f"Indexed {what}. Keyword search can see them now."]
        if self._embed is not None:
            lines.append(
                f"Embeddings will land after this turn ({self._embed_model}) "
                "if that model is pulled."
            )
        else:
            lines.append(
                "No embed model is configured; keyword search only."
            )
        return ToolResult(
            ok=True,
            output=" ".join(lines),
            data={
                "files": files,
                "chunks": chunks,
                "mail": mail,
                "source": source,
                "path": path,
                "embedded": False,
            },
        )


async def _call_index(
    fn: IndexFn, path: str | None
) -> tuple[int, int | None]:
    """Run a sync-or-async index hook. Never the embed path."""
    if path:
        try:
            out = fn(path)
        except TypeError:
            try:
                out = fn(under=path)
            except TypeError:
                out = fn()
    else:
        out = fn()
    if inspect.isawaitable(out):
        out = await out
    if isinstance(out, tuple) and len(out) >= 2:
        return int(out[0]), int(out[1])
    return int(out), None


def _clamp_limit(value: Any, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(_MAX_LIMIT, n))


def _resolve_offset(kwargs: dict[str, Any], *, limit: int) -> int:
    """Return a non-negative offset; page is 1-based when offset is omitted."""
    raw_offset = kwargs.get("offset")
    if raw_offset is not None and str(raw_offset).strip() != "":
        try:
            return max(0, int(raw_offset))
        except (TypeError, ValueError):
            return 0
    raw_page = kwargs.get("page")
    if raw_page is None or str(raw_page).strip() == "":
        return 0
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        return 0
    if page < 1:
        page = 1
    return (page - 1) * limit


def _excerpt(text: str, *, limit: int = _EXCERPT_CHARS) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _format_when(iso: str) -> str:
    if not iso:
        return "unknown date"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return dt.strftime("%d %B %Y").lstrip("0")


def _format_hit(hit: SearchHit) -> str:
    when = _format_when(hit.created_at)
    if hit.source == "doc":
        path = hit.path or hit.title or "(file)"
        return f"- [{when}] file={path}: {_excerpt(hit.content)}"
    if hit.source == "mail":
        subject = hit.title.strip() or "(no subject)"
        return f"- [{when}] mail={hit.path or subject}: {_excerpt(hit.content)}"
    title = hit.title.strip() or "(untitled)"
    return (
        f"- [{when}] session={hit.session_id} ({title}) "
        f"{hit.role}: {_excerpt(hit.content)}"
    )
