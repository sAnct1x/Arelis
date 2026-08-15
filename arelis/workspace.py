from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from arelis.config import PROJECT_ROOT

log = logging.getLogger(__name__)

# Last active project name, restored on the next launch (Cursor-style).
_ACTIVE_PROJECT_FILE = PROJECT_ROOT / "data" / "active_project"

# Windows drive paths use a colon; never treat "C:\..." as project "C".
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:(?:[\\/]|$)")


class AmbiguousPathError(ValueError):
    """Bare path matched more than one configured root."""


@dataclass(frozen=True)
class RootEntry:
    name: str
    path: Path
    read_only: bool = False


@dataclass(frozen=True)
class ResolvedPath:
    """A sandbox hit: real path plus which named root contained it."""

    path: Path
    root_name: str
    root: Path

    def qualified(self, *, multi: bool) -> str:
        """Identity safe to store in the memory trace.

        Single-root sessions keep bare relative paths (unchanged behaviour).
        Multi-root sessions always qualify so a later project switch cannot
        re-anchor "that file" to a different project.
        """
        try:
            rel = self.path.relative_to(self.root).as_posix()
        except ValueError:
            return str(self.path)
        if rel == ".":
            rel = ""
        if not multi:
            return rel or "."
        return f"{self.root_name}:{rel}" if rel else f"{self.root_name}:"


class WorkspaceRoots:
    """Named workspace roots plus one session-shared active project.

    This is the choke point for path identity. Both file-touching tools hold the
    same instance so /project, the dock switcher, and bare-path writes agree.
    """

    def __init__(self, roots: list[RootEntry], active: str | None = None) -> None:
        if not roots:
            raise ValueError("No workspace roots are configured")
        seen: set[str] = set()
        for root in roots:
            if root.name in seen:
                raise ValueError(
                    f"Duplicate workspace root name `{root.name}`; "
                    "give each root an explicit unique name in config"
                )
            seen.add(root.name)
        self._roots = list(roots)
        self._by_name = {r.name: r for r in self._roots}
        if active and active in self._by_name:
            self._active = active
        else:
            if active:
                log.warning(
                    "Active project `%s` is not a configured root; using `%s`",
                    active,
                    self._roots[0].name,
                )
            self._active = self._roots[0].name
        # Session-only absolute paths the user granted for read (attach / Allow).
        # Never used for write/create. Cleared on clear_external_reads().
        self._external_reads: set[Path] = set()

    def __len__(self) -> int:
        return len(self._roots)

    @property
    def active(self) -> str:
        return self._active

    @property
    def roots(self) -> list[RootEntry]:
        return list(self._roots)

    def names(self) -> list[str]:
        return [r.name for r in self._roots]

    def active_root(self) -> RootEntry:
        return self._by_name[self._active]

    def set_active(self, name: str, *, persist: bool = True) -> None:
        if name not in self._by_name:
            known = ", ".join(self.names())
            raise ValueError(f"Unknown project `{name}`. Choose one of: {known}")
        self._active = name
        if persist:
            save_active_project(name)

    def replace_roots(
        self,
        roots: list[RootEntry],
        *,
        preferred_active: str | None = None,
        persist: bool = True,
    ) -> None:
        """Hot-swap configured roots (Settings) while keeping session grants."""
        if not roots:
            raise ValueError("No workspace roots are configured")
        seen: set[str] = set()
        for root in roots:
            if root.name in seen:
                raise ValueError(
                    f"Duplicate workspace root name `{root.name}`; "
                    "give each root an explicit unique name in config"
                )
            seen.add(root.name)
        self._roots = list(roots)
        self._by_name = {r.name: r for r in self._roots}
        want = preferred_active or self._active
        if want in self._by_name:
            self._active = want
        else:
            if preferred_active:
                log.warning(
                    "Active project `%s` is not a configured root; using `%s`",
                    preferred_active,
                    self._roots[0].name,
                )
            self._active = self._roots[0].name
        if persist:
            save_active_project(self._active)

    @classmethod
    def from_paths(cls, paths: list[str], *, active: str | None = None) -> WorkspaceRoots:
        """Build from a flat path list (tests and back-compat)."""
        entries: list[RootEntry] = []
        used: dict[str, int] = {}
        for raw in paths:
            path = Path(raw).resolve()
            base = path.name or "root"
            count = used.get(base, 0)
            used[base] = count + 1
            name = base if count == 0 else f"{base}-{count + 1}"
            entries.append(RootEntry(name=name, path=path))
        return cls(entries, active=active)

    @classmethod
    def from_config(cls, config: dict) -> WorkspaceRoots:
        workspace = config.get("workspace") or {}
        raw_roots = workspace.get("named_roots")
        if not raw_roots:
            # Flat absolute paths left by older loaders / tests.
            flat = workspace.get("roots") or ["."]
            if flat and isinstance(flat[0], dict):
                raw_roots = flat
            else:
                return cls.from_paths([str(p) for p in flat], active=load_active_project())
        entries = [
            RootEntry(
                name=str(item["name"]),
                path=Path(str(item["path"])).resolve(),
                read_only=bool(item.get("read_only", False)),
            )
            for item in raw_roots
        ]
        return cls(entries, active=load_active_project())

    def grant_external_read(self, path: Path | str) -> Path | None:
        """Allow read-only resolve of an absolute path for this UI session.

        Returns the normalized path when granted, or None when the path cannot
        be resolved / is not a usable file or directory.
        """
        raw = str(path or "").strip()
        if not raw:
            return None
        try:
            resolved = Path(raw).expanduser().resolve()
        except OSError:
            return None
        if not resolved.exists():
            return None
        self._external_reads.add(resolved)
        # Also grant the parent when a file was attached so list of that folder
        # is not needed — only the exact path. Directories are grantable too.
        return resolved

    def clear_external_reads(self) -> None:
        """Drop all session grants (call on UI quit)."""
        self._external_reads.clear()

    def has_external_read(self, path: Path | str) -> bool:
        try:
            resolved = Path(path).expanduser().resolve()
        except OSError:
            return False
        return resolved in self._external_reads

    def resolve(
        self,
        path_str: str,
        *,
        for_create: bool = False,
        for_write: bool = False,
    ) -> ResolvedPath:
        """Map a caller path to a real path inside an allowed root.

        Qualifiers are config keys only — never joined into the filesystem path
        before the name→root lookup. resolve() runs before the containment test
        so ".." and symlinks cannot escape. External read grants are never used
        here — use resolve_read() for list/read/analyze/vision/doc_extract.

        for_create and for_write both reject read_only roots (edit uses for_write).
        """
        return self._resolve_inner(
            path_str,
            for_create=for_create,
            allow_external=False,
            for_write=for_write or for_create,
        )

    def resolve_read(self, path_str: str) -> ResolvedPath:
        """Like resolve() for reads, but also accepts session-granted absolutes."""
        return self._resolve_inner(
            path_str, for_create=False, allow_external=True, for_write=False
        )

    def _resolve_inner(
        self,
        path_str: str,
        *,
        for_create: bool,
        allow_external: bool,
        for_write: bool,
    ) -> ResolvedPath:
        raw = (path_str or "").strip()
        if not raw:
            raise ValueError("Missing path")

        qualified = _split_qualified(raw, set(self._by_name))
        if qualified is not None:
            name, rest = qualified
            entry = self._by_name[name]
            rel = Path(rest) if rest else Path(".")
            if rel.is_absolute():
                raise PermissionError(
                    f"Qualified path must be relative to project `{name}`, got: {rest}"
                )
            path = (entry.path / rel).resolve()
            if not for_create:
                path = _soften_existing(path)
            return self._contain(path, entry, for_write=for_write)

        path = Path(raw)
        if path.is_absolute() or _WINDOWS_DRIVE.match(raw):
            path = path.resolve()
            if not for_create:
                path = _soften_existing(path)
            try:
                return self._contain_any(path, for_write=for_write)
            except PermissionError:
                if allow_external and not for_create and path in self._external_reads:
                    return ResolvedPath(
                        path=path,
                        root_name="external",
                        root=path.parent if path.is_file() else path,
                    )
                raise

        # Bare relative.
        if len(self._roots) == 1:
            entry = self._roots[0]
            path = (entry.path / path).resolve()
            if not for_create:
                path = _soften_existing(path)
            return self._contain(path, entry, for_write=for_write)

        hits: list[ResolvedPath] = []
        for entry in self._roots:
            candidate = (entry.path / path).resolve()
            try:
                candidate.relative_to(entry.path)
            except ValueError:
                continue
            if not for_create:
                candidate = _soften_existing(candidate)
            if candidate.exists():
                hits.append(ResolvedPath(path=candidate, root_name=entry.name, root=entry.path))

        if len(hits) == 1:
            return self._contain(
                hits[0].path,
                self._by_name[hits[0].root_name],
                for_write=for_write,
            )
        if len(hits) > 1:
            labels = ", ".join(f"{h.root_name}:{path.as_posix()}" for h in hits)
            raise AmbiguousPathError(
                f"Path `{raw}` matches more than one project ({labels}); "
                "qualify it as name:path"
            )

        # Zero hits: new files and missing reads anchor to the active project.
        # for_create names the write case; both share this anchor so a bare
        # create never falls back to roots[0] by habit after a project switch.
        entry = self.active_root()
        anchored = (entry.path / path).resolve()
        if not for_create:
            anchored = _soften_existing(anchored)
        return self._contain(anchored, entry, for_write=for_write)

    def _contain(
        self, path: Path, entry: RootEntry, *, for_write: bool = False
    ) -> ResolvedPath:
        try:
            path.relative_to(entry.path)
        except ValueError as exc:
            raise PermissionError(f"Path outside allowed workspace roots: {path}") from exc
        if for_write and entry.read_only:
            raise PermissionError(
                f"Workspace root `{entry.name}` is read-only; cannot write or edit"
            )
        return ResolvedPath(path=path, root_name=entry.name, root=entry.path)

    def _contain_any(self, path: Path, *, for_write: bool = False) -> ResolvedPath:
        for entry in self._roots:
            try:
                path.relative_to(entry.path)
                return self._contain(path, entry, for_write=for_write)
            except ValueError:
                continue
        raise PermissionError(f"Path outside allowed workspace roots: {path}")

    def prompt_line(self) -> str | None:
        """Short system line for multi-root sessions. Names only; None if single-root."""
        if len(self._roots) == 1:
            entry = self._roots[0]
            if entry.read_only:
                return (
                    f"Active project: {self._active} (read-only). "
                    "Do not write or edit files under this root."
                )
            return None
        others = [n for n in self.names() if n != self._active]
        other_txt = ", ".join(others) if others else "(none)"
        ro = [r.name for r in self._roots if r.read_only]
        line = (
            f"Active project: {self._active}. "
            f"Other projects: {other_txt}. "
            f"Qualify paths as name:relative/path when the project is not the active one."
        )
        if ro:
            line += f" Read-only roots (no write/edit): {', '.join(ro)}."
        return line


def _soften_existing(path: Path) -> Path:
    """Case-insensitive / extension-tolerant lookup for human Open paths.

    Operators type `readme` or wrong-case stems; exact Path joins miss
    `README.md`. Only remaps when a unique sibling (or unique stem match)
    exists — never invents a path for creates.
    """
    if path.exists():
        return path
    parent = path.parent
    if not parent.is_dir():
        return path
    wanted = path.name.casefold()
    wanted_stem = path.stem.casefold()
    try:
        entries = list(parent.iterdir())
    except OSError:
        return path
    exact = [p for p in entries if p.name.casefold() == wanted]
    if len(exact) == 1:
        return exact[0]
    # Stem-only typed names (`readme` → `README.md`) when unique among files.
    if not path.suffix:
        stems = [p for p in entries if p.is_file() and p.stem.casefold() == wanted_stem]
        if len(stems) == 1:
            return stems[0]
    return path


def _split_qualified(raw: str, names: set[str]) -> tuple[str, str] | None:
    """Return (name, relative) if raw uses name:path against a known project."""
    if _WINDOWS_DRIVE.match(raw):
        return None
    if ":" not in raw:
        return None
    name, rest = raw.split(":", 1)
    if name not in names:
        raise PermissionError(
            f"Unknown project `{name}`. Known projects: {', '.join(sorted(names))}"
        )
    return name, rest


def load_active_project() -> str | None:
    try:
        text = _ACTIVE_PROJECT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def save_active_project(name: str) -> None:
    _ACTIVE_PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ACTIVE_PROJECT_FILE.write_text(name.strip() + "\n", encoding="utf-8")


def compose_stt_initial_prompt(config: dict, workspace: WorkspaceRoots) -> str:
    """Bias Whisper toward wake/jargon seed, then at most two project names.

    Seed first so project names cannot bury "Hey Arelis". Keep the whole string
    short — Whisper often regurgitates a long initial_prompt as the transcript.
    """
    stt = (config.get("voice") or {}).get("stt") or {}
    seed = str(stt.get("initial_prompt") or "").strip() or "Hey Arelis."
    # Cap project bias: long name lists become prompt-echo garbage.
    names = ", ".join(workspace.names()[:2])
    parts = [p for p in (seed, names) if p]
    joined = ", ".join(parts)
    if len(joined) > 120:
        return seed[:120]
    return joined
