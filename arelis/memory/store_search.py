"""Keyword search, FTS, documents, mail, embeddings, and vector search."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import numpy as np

from arelis.memory.store import SearchHit, _fts_match, _inserted_id, _utc_now, log

if TYPE_CHECKING:
    from arelis.memory.store import MemoryStore

def search(store: MemoryStore, query: str, *, limit: int = 20) -> list[SearchHit]:
    """Keyword search across archived messages.

    Uses FTS5 when the bundled SQLite has it; otherwise LIKE. Callers that
    need to tell the user which path ran can read fts_available.
    """
    cleaned = query.strip()
    if not cleaned:
        return []
    if store._fts:
        return store._search_fts(cleaned, limit=limit)
    return store._search_like(cleaned, limit=limit)

def search_documents(store: MemoryStore, query: str, *, limit: int = 20) -> list[SearchHit]:
    """Keyword search across indexed workspace file chunks."""
    cleaned = query.strip()
    if not cleaned:
        return []
    if store._fts:
        return store._search_documents_fts(cleaned, limit=limit)
    return store._search_documents_like(cleaned, limit=limit)

def list_documents(store: MemoryStore) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT id, root_name, rel_path, mtime_ns, size, indexed_at
        FROM documents
        ORDER BY root_name, rel_path
        """
    ).fetchall()
    return [dict(row) for row in rows]

def get_document(store: MemoryStore, root_name: str, rel_path: str) -> dict[str, Any] | None:
    row = store._conn.execute(
        """
        SELECT id, root_name, rel_path, mtime_ns, size, indexed_at
        FROM documents
        WHERE root_name = ? AND rel_path = ?
        """,
        (root_name, rel_path),
    ).fetchone()
    return dict(row) if row else None

def replace_document_chunks(
    store: MemoryStore,
    *,
    root_name: str,
    rel_path: str,
    mtime_ns: int,
    size: int,
    chunks: list[str],
) -> int:
    """Upsert a document and replace its chunks. Returns document id."""
    now = _utc_now()
    existing = store.get_document(root_name, rel_path)
    if existing is None:
        cur = store._conn.execute(
            """
            INSERT INTO documents (root_name, rel_path, mtime_ns, size, indexed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (root_name, rel_path, int(mtime_ns), int(size), now),
        )
        doc_id = _inserted_id(cur)
    else:
        doc_id = int(existing["id"])
        store._conn.execute(
            """
            UPDATE documents
            SET mtime_ns = ?, size = ?, indexed_at = ?
            WHERE id = ?
            """,
            (int(mtime_ns), int(size), now, doc_id),
        )
        store._conn.execute(
            "DELETE FROM document_chunks WHERE document_id = ?", (doc_id,)
        )
    for ordinal, text in enumerate(chunks):
        cleaned = text.strip()
        if not cleaned:
            continue
        store._conn.execute(
            """
            INSERT INTO document_chunks (document_id, ordinal, content)
            VALUES (?, ?, ?)
            """,
            (doc_id, ordinal, cleaned),
        )
    store._conn.commit()
    return doc_id

def delete_documents_not_in(store: MemoryStore, keep: set[tuple[str, str]]) -> int:
    """Drop indexed files that no longer exist on disk. Returns rows removed."""
    rows = store.list_documents()
    removed = 0
    for row in rows:
        key = (str(row["root_name"]), str(row["rel_path"]))
        if key in keep:
            continue
        store._conn.execute("DELETE FROM documents WHERE id = ?", (int(row["id"]),))
        removed += 1
    if removed:
        store._conn.commit()
    return removed

def unembedded_document_chunks(store: MemoryStore, *, limit: int = 32) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT c.id, c.content
        FROM document_chunks c
        LEFT JOIN document_embeddings e ON e.chunk_id = c.id
        WHERE e.chunk_id IS NULL
          AND length(trim(c.content)) > 0
        ORDER BY c.id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]

def upsert_document_embedding(
    store: MemoryStore,
    chunk_id: int,
    model: str,
    vector: list[float] | np.ndarray,
) -> None:
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return
    store._conn.execute(
        """
        INSERT INTO document_embeddings (chunk_id, model, dims, vector)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chunk_id) DO UPDATE SET
            model = excluded.model,
            dims = excluded.dims,
            vector = excluded.vector
        """,
        (int(chunk_id), model, int(arr.size), arr.tobytes()),
    )
    store._conn.commit()

def vector_search_documents(
    store: MemoryStore,
    query: list[float] | np.ndarray,
    *,
    model: str,
    limit: int = 20,
) -> list[SearchHit]:
    q = np.asarray(query, dtype=np.float32).reshape(-1)
    if q.size == 0:
        return []
    q_norm = float(np.linalg.norm(q))
    if q_norm == 0.0:
        return []
    q = q / q_norm
    rows = store._conn.execute(
        """
        SELECT e.chunk_id, e.dims, e.vector,
               c.content, d.root_name, d.rel_path, d.indexed_at
        FROM document_embeddings e
        JOIN document_chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE e.model = ?
        """,
        (model,),
    ).fetchall()
    if not rows:
        return []
    meta: list[sqlite3.Row] = []
    vectors: list[np.ndarray] = []
    for row in rows:
        dims = int(row["dims"])
        vec = np.frombuffer(row["vector"], dtype=np.float32)
        if vec.size != dims or vec.size != q.size:
            continue
        meta.append(row)
        vectors.append(vec)
    if not vectors:
        return []
    matrix = np.stack(vectors, axis=0)
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0.0] = 1.0
    scores = (matrix / norms[:, None]) @ q
    order = np.argsort(-scores)[:limit]
    hits: list[SearchHit] = []
    for idx in order:
        row = meta[int(idx)]
        hits.append(store._doc_hit(row))
    return hits

def search_mail(store: MemoryStore, query: str, *, limit: int = 20) -> list[SearchHit]:
    cleaned = query.strip()
    if not cleaned:
        return []
    if store._fts:
        return store._search_mail_fts(cleaned, limit=limit)
    return store._search_mail_like(cleaned, limit=limit)

def upsert_mail_message(
    store: MemoryStore,
    *,
    uid: str,
    sender: str,
    subject: str,
    date_text: str,
    unread: bool,
    body: str,
) -> int:
    """Insert or replace one peeked mail message. Returns its row id."""
    now = _utc_now()
    existing = store._conn.execute(
        "SELECT id FROM mail_messages WHERE uid = ?", (uid,)
    ).fetchone()
    if existing is None:
        cur = store._conn.execute(
            """
            INSERT INTO mail_messages
                (uid, sender, subject, date_text, unread, body, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                sender,
                subject,
                date_text,
                1 if unread else 0,
                body,
                now,
            ),
        )
        mail_id = _inserted_id(cur)
    else:
        mail_id = int(existing["id"])
        store._conn.execute(
            """
            UPDATE mail_messages
            SET sender = ?, subject = ?, date_text = ?, unread = ?,
                body = ?, indexed_at = ?
            WHERE id = ?
            """,
            (
                sender,
                subject,
                date_text,
                1 if unread else 0,
                body,
                now,
                mail_id,
            ),
        )
        # Body change invalidates the old vector.
        store._conn.execute(
            "DELETE FROM mail_embeddings WHERE mail_id = ?", (mail_id,)
        )
    store._conn.commit()
    return mail_id

def delete_mail_not_in(store: MemoryStore, keep_uids: set[str]) -> int:
    rows = store._conn.execute("SELECT id, uid FROM mail_messages").fetchall()
    removed = 0
    for row in rows:
        if str(row["uid"]) in keep_uids:
            continue
        store._conn.execute("DELETE FROM mail_messages WHERE id = ?", (int(row["id"]),))
        removed += 1
    if removed:
        store._conn.commit()
    return removed

def unembedded_mail(store: MemoryStore, *, limit: int = 32) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT m.id, m.subject, m.sender, m.body
        FROM mail_messages m
        LEFT JOIN mail_embeddings e ON e.mail_id = m.id
        WHERE e.mail_id IS NULL
        ORDER BY m.id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        text = f"{row['subject']}\nFrom: {row['sender']}\n\n{row['body']}"
        out.append({"id": int(row["id"]), "content": text})
    return out

def upsert_mail_embedding(
    store: MemoryStore,
    mail_id: int,
    model: str,
    vector: list[float] | np.ndarray,
) -> None:
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return
    store._conn.execute(
        """
        INSERT INTO mail_embeddings (mail_id, model, dims, vector)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(mail_id) DO UPDATE SET
            model = excluded.model,
            dims = excluded.dims,
            vector = excluded.vector
        """,
        (int(mail_id), model, int(arr.size), arr.tobytes()),
    )
    store._conn.commit()

def vector_search_mail(
    store: MemoryStore,
    query: list[float] | np.ndarray,
    *,
    model: str,
    limit: int = 20,
) -> list[SearchHit]:
    q = np.asarray(query, dtype=np.float32).reshape(-1)
    if q.size == 0:
        return []
    q_norm = float(np.linalg.norm(q))
    if q_norm == 0.0:
        return []
    q = q / q_norm
    rows = store._conn.execute(
        """
        SELECT e.mail_id, e.dims, e.vector,
               m.uid, m.sender, m.subject, m.date_text, m.body, m.indexed_at
        FROM mail_embeddings e
        JOIN mail_messages m ON m.id = e.mail_id
        WHERE e.model = ?
        """,
        (model,),
    ).fetchall()
    if not rows:
        return []
    meta: list[sqlite3.Row] = []
    vectors: list[np.ndarray] = []
    for row in rows:
        dims = int(row["dims"])
        vec = np.frombuffer(row["vector"], dtype=np.float32)
        if vec.size != dims or vec.size != q.size:
            continue
        meta.append(row)
        vectors.append(vec)
    if not vectors:
        return []
    matrix = np.stack(vectors, axis=0)
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0.0] = 1.0
    scores = (matrix / norms[:, None]) @ q
    order = np.argsort(-scores)[:limit]
    return [store._mail_hit(meta[int(idx)]) for idx in order]

def unembedded_messages(store: MemoryStore, *, limit: int = 32) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT m.id, m.content
        FROM messages m
        LEFT JOIN embeddings e ON e.message_id = m.id
        WHERE e.message_id IS NULL
          AND length(trim(m.content)) > 0
        ORDER BY m.id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]

def upsert_embedding(
    store: MemoryStore,
    message_id: int,
    model: str,
    vector: list[float] | np.ndarray,
) -> None:
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return
    store._conn.execute(
        """
        INSERT INTO embeddings (message_id, model, dims, vector)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            model = excluded.model,
            dims = excluded.dims,
            vector = excluded.vector
        """,
        (int(message_id), model, int(arr.size), arr.tobytes()),
    )
    store._conn.commit()

def vector_search(
    store: MemoryStore,
    query: list[float] | np.ndarray,
    *,
    model: str,
    limit: int = 20,
) -> list[SearchHit]:
    """Nearest messages by cosine similarity for one embedding model."""
    q = np.asarray(query, dtype=np.float32).reshape(-1)
    if q.size == 0:
        return []
    q_norm = float(np.linalg.norm(q))
    if q_norm == 0.0:
        return []
    q = q / q_norm

    rows = store._conn.execute(
        """
        SELECT e.message_id, e.dims, e.vector,
               m.session_id, m.role, m.content, m.created_at, s.title
        FROM embeddings e
        JOIN messages m ON m.id = e.message_id
        JOIN sessions s ON s.id = m.session_id
        WHERE e.model = ?
          AND m.role != 'notice'
        """,
        (model,),
    ).fetchall()
    if not rows:
        return []

    ids: list[int] = []
    meta: list[sqlite3.Row] = []
    vectors: list[np.ndarray] = []
    for row in rows:
        dims = int(row["dims"])
        raw = row["vector"]
        vec = np.frombuffer(raw, dtype=np.float32)
        if vec.size != dims or vec.size != q.size:
            continue
        ids.append(int(row["message_id"]))
        meta.append(row)
        vectors.append(vec)

    if not vectors:
        return []

    matrix = np.stack(vectors, axis=0)
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0.0] = 1.0
    scores = (matrix / norms[:, None]) @ q
    order = np.argsort(-scores)[:limit]
    hits: list[SearchHit] = []
    for idx in order:
        row = meta[int(idx)]
        hits.append(
            SearchHit(
                message_id=int(row["message_id"]),
                session_id=str(row["session_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
                title=str(row["title"] or ""),
                source="chat",
            )
        )
    return hits

def _search_fts(store: MemoryStore, query: str, *, limit: int) -> list[SearchHit]:
    # Quote each token so punctuation in the user's words cannot break
    # the FTS query syntax; MATCH still does prefix-friendly AND of terms.
    match = _fts_match(query)
    if not match:
        return []
    rows = store._conn.execute(
        """
        SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title
        FROM messages_fts
        JOIN messages m ON m.id = messages_fts.rowid
        JOIN sessions s ON s.id = m.session_id
        WHERE messages_fts MATCH ?
          AND m.role != 'notice'
        ORDER BY m.created_at DESC
        LIMIT ?
        """,
        (match, limit),
    ).fetchall()
    return [
        SearchHit(
            message_id=int(row["id"]),
            session_id=str(row["session_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=str(row["created_at"]),
            title=str(row["title"] or ""),
            source="chat",
        )
        for row in rows
    ]

def _search_like(store: MemoryStore, query: str, *, limit: int) -> list[SearchHit]:
    pattern = f"%{query}%"
    rows = store._conn.execute(
        """
        SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE (m.content LIKE ? OR m.note LIKE ?)
          AND m.role != 'notice'
        ORDER BY m.created_at DESC
        LIMIT ?
        """,
        (pattern, pattern, limit),
    ).fetchall()
    return [
        SearchHit(
            message_id=int(row["id"]),
            session_id=str(row["session_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=str(row["created_at"]),
            title=str(row["title"] or ""),
            source="chat",
        )
        for row in rows
    ]

def _search_documents_fts(store: MemoryStore, query: str, *, limit: int) -> list[SearchHit]:
    match = _fts_match(query)
    if not match:
        return []
    rows = store._conn.execute(
        """
        SELECT c.id, c.content, d.root_name, d.rel_path, d.indexed_at
        FROM document_chunks_fts
        JOIN document_chunks c ON c.id = document_chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE document_chunks_fts MATCH ?
        ORDER BY d.indexed_at DESC
        LIMIT ?
        """,
        (match, limit),
    ).fetchall()
    return [store._doc_hit(row) for row in rows]

def _search_documents_like(store: MemoryStore, query: str, *, limit: int) -> list[SearchHit]:
    pattern = f"%{query}%"
    rows = store._conn.execute(
        """
        SELECT c.id, c.content, d.root_name, d.rel_path, d.indexed_at
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.content LIKE ?
        ORDER BY d.indexed_at DESC
        LIMIT ?
        """,
        (pattern, limit),
    ).fetchall()
    return [store._doc_hit(row) for row in rows]

def _doc_hit(store: MemoryStore, row: sqlite3.Row) -> SearchHit:
    root = str(row["root_name"])
    rel = str(row["rel_path"])
    path = f"{root}:{rel}" if rel else f"{root}:"
    chunk_id = int(row["id"] if "id" in row.keys() else row["chunk_id"])
    return SearchHit(
        message_id=chunk_id,
        session_id="",
        role="file",
        content=str(row["content"]),
        created_at=str(row["indexed_at"] or ""),
        title=path,
        source="doc",
        path=path,
        chunk_id=chunk_id,
    )

def _search_mail_fts(store: MemoryStore, query: str, *, limit: int) -> list[SearchHit]:
    match = _fts_match(query)
    if not match:
        return []
    rows = store._conn.execute(
        """
        SELECT m.id, m.uid, m.sender, m.subject, m.date_text, m.body, m.indexed_at
        FROM mail_messages_fts
        JOIN mail_messages m ON m.id = mail_messages_fts.rowid
        WHERE mail_messages_fts MATCH ?
        ORDER BY m.indexed_at DESC
        LIMIT ?
        """,
        (match, limit),
    ).fetchall()
    return [store._mail_hit(row) for row in rows]

def _search_mail_like(store: MemoryStore, query: str, *, limit: int) -> list[SearchHit]:
    pattern = f"%{query}%"
    rows = store._conn.execute(
        """
        SELECT id, uid, sender, subject, date_text, body, indexed_at
        FROM mail_messages
        WHERE subject LIKE ? OR sender LIKE ? OR body LIKE ?
        ORDER BY indexed_at DESC
        LIMIT ?
        """,
        (pattern, pattern, pattern, limit),
    ).fetchall()
    return [store._mail_hit(row) for row in rows]

def _mail_hit(store: MemoryStore, row: sqlite3.Row) -> SearchHit:
    mail_id = int(row["id"] if "id" in row.keys() else row["mail_id"])
    uid = str(row["uid"])
    subject = str(row["subject"] or "(no subject)")
    sender = str(row["sender"] or "")
    body = str(row["body"] or "")
    content = f"From: {sender}\nSubject: {subject}\n\n{body}"
    return SearchHit(
        message_id=mail_id,
        session_id="",
        role="mail",
        content=content,
        created_at=str(row["date_text"] or row["indexed_at"] or ""),
        title=subject,
        source="mail",
        path=f"mail:{uid}",
        chunk_id=mail_id,
    )

def _probe_fts(store: MemoryStore) -> bool:
    try:
        store._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _arelis_fts_probe USING fts5(x)")
        store._conn.execute("DROP TABLE _arelis_fts_probe")
        return True
    except sqlite3.OperationalError:
        log.warning("FTS5 unavailable; memory search will use LIKE")
        return False
