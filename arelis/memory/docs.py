"""Index readable workspace files into the memory archive.

Runs between turns with the message embedder. Files stay inside WorkspaceRoots;
binaries, huge files, and junk directories are skipped. Re-index is driven by
mtime so an idle tick only rewrites what changed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from arelis.memory.store import MemoryStore
from arelis.workspace import WorkspaceRoots

log = logging.getLogger(__name__)

_TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".csv",
        ".tsv",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".cs",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sql",
        ".sh",
        ".bash",
        ".ps1",
        ".bat",
        ".cmd",
        ".xml",
        ".svg",
        ".tex",
        ".bib",
        ".r",
        ".rb",
        ".php",
        ".swift",
        ".lua",
        ".gradle",
        ".cmake",
        ".makefile",
        ".mk",
    }
)

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "outputs",
        "logs",
        ".cursor",
    }
)

DEFAULT_MAX_FILE_BYTES = 512_000
DEFAULT_CHUNK_CHARS = 1200
DEFAULT_CHUNK_OVERLAP = 200


def chunk_text(
    text: str,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping windows. Prefer paragraph boundaries when cheap."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_chars:
        return [cleaned]
    overlap = max(0, min(overlap, chunk_chars // 2))
    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + chunk_chars, length)
        if end < length:
            # Prefer breaking at a blank line, then a newline, then a space.
            window = cleaned[start:end]
            break_at = window.rfind("\n\n")
            if break_at < chunk_chars // 3:
                break_at = window.rfind("\n")
            if break_at < chunk_chars // 3:
                break_at = window.rfind(" ")
            if break_at >= chunk_chars // 3:
                end = start + break_at
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


def looks_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    # High ratio of non-text bytes => skip.
    textish = sum(1 for b in sample if 9 <= b <= 13 or 32 <= b < 127)
    return (textish / len(sample)) < 0.85


class DocumentIndexer:
    """Walk workspace roots and keep document_chunks in sync."""

    def __init__(
        self,
        store: MemoryStore,
        workspace: WorkspaceRoots,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        chunk_chars: int = DEFAULT_CHUNK_CHARS,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        self.store = store
        self.workspace = workspace
        self.max_file_bytes = max_file_bytes
        self.chunk_chars = chunk_chars
        self.chunk_overlap = chunk_overlap

    def sync_batch(self, *, max_files: int = 8) -> int:
        """Reindex up to max_files that are new or changed. Prune missing paths."""
        candidates = list(self._iter_files())
        keep = {(root, rel) for root, rel, _path in candidates}
        removed = self.store.delete_documents_not_in(keep)
        if removed:
            log.info("Removed %d stale document(s) from the archive", removed)

        dirty: list[tuple[str, str, Path]] = []
        for root_name, rel_path, path in candidates:
            try:
                st = path.stat()
            except OSError:
                continue
            existing = self.store.get_document(root_name, rel_path)
            mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
            size = int(st.st_size)
            if (
                existing is not None
                and int(existing["mtime_ns"]) == mtime_ns
                and int(existing["size"]) == size
            ):
                continue
            dirty.append((root_name, rel_path, path))

        written = 0
        for root_name, rel_path, path in dirty[:max_files]:
            if self._index_file(root_name, rel_path, path):
                written += 1
        if written:
            log.info("Indexed %d workspace file(s) into memory", written)
        return written

    def _iter_files(self) -> list[tuple[str, str, Path]]:
        found: list[tuple[str, str, Path]] = []
        for root in self.workspace.roots:
            root_path = root.path
            if not root_path.is_dir():
                continue
            for path in root_path.rglob("*"):
                if not path.is_file():
                    continue
                if any(part in _SKIP_DIR_NAMES for part in path.parts):
                    continue
                suffix = path.suffix.lower()
                name = path.name.lower()
                if suffix not in _TEXT_SUFFIXES and name not in {
                    "makefile",
                    "dockerfile",
                    "readme",
                    "license",
                    "licence",
                }:
                    continue
                try:
                    rel = path.resolve().relative_to(root_path.resolve()).as_posix()
                except ValueError:
                    continue
                found.append((root.name, rel, path))
        found.sort(key=lambda item: (item[0], item[1]))
        return found

    def _index_file(self, root_name: str, rel_path: str, path: Path) -> bool:
        try:
            st = path.stat()
        except OSError as exc:
            log.debug("Skip %s: %s", path, exc)
            return False
        if st.st_size > self.max_file_bytes:
            log.debug("Skip %s: %d bytes over cap", path, st.st_size)
            return False
        try:
            raw = path.read_bytes()
        except OSError as exc:
            log.debug("Skip %s: %s", path, exc)
            return False
        if looks_binary(raw[:8192]):
            return False
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                return False
        chunks = chunk_text(
            text, chunk_chars=self.chunk_chars, overlap=self.chunk_overlap
        )
        if not chunks:
            return False
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
        self.store.replace_document_chunks(
            root_name=root_name,
            rel_path=rel_path,
            mtime_ns=mtime_ns,
            size=int(st.st_size),
            chunks=chunks,
        )
        return True
