"""Workspace roots and editor file IO. Window methods stay as delegates."""

from __future__ import annotations

from pathlib import Path

from arelis.config import _parse_workspace_roots, merge_local_config
from arelis.core.failure_copy import plain_reason
from arelis.desk import DeskStore, infer_kind, is_image_kind, is_text_kind, write_note
from arelis.local_open import open_local_file, reveal_local_file
from arelis.ui.dialog import ask_text
from arelis.ui.layout_store import push_recent_workspace_file
from arelis.workspace import RootEntry


def apply_workspace_roots(
    window,
    roots: list[dict[str, object]],
    *,
    preferred_active: str | None = None,
) -> None:
    """Persist named roots to config.local.yaml and hot-refresh the shared sandbox."""
    if not roots:
        window.thinking.append("Keep at least one workspace root.", kind="status")
        return
    try:
        named = _parse_workspace_roots(roots)
    except Exception as exc:
        window.thinking.append(f"Workspace roots rejected: {exc}", kind="status")
        return
    merge_local_config({"workspace": {"roots": named}})
    entries = [
        RootEntry(
            name=str(item["name"]),
            path=Path(str(item["path"])).resolve(),
            read_only=bool(item.get("read_only", False)),
        )
        for item in named
    ]
    want = preferred_active or window.workspace_roots.active
    try:
        window.workspace_roots.replace_roots(entries, preferred_active=want)
    except Exception as exc:
        window.thinking.append(f"Workspace roots update failed: {exc}", kind="status")
        return
    window.config.setdefault("workspace", {})
    window.config["workspace"]["named_roots"] = named
    window.config["workspace"]["roots"] = [entry["path"] for entry in named]
    window.config["_workspace"] = window.workspace_roots
    window.workspace.set_projects(
        window.workspace_roots.names(),
        window.workspace_roots.active,
        paths={r.name: str(r.path) for r in window.workspace_roots.roots},
    )
    window.thinking.append(
        f"Workspace roots updated ({len(entries)}): "
        + ", ".join(window.workspace_roots.names()),
        kind="status",
    )
    refresh_desk(window)


def workspace_root_dicts(window) -> list[dict[str, object]]:
    return [
        {
            "name": entry.name,
            "path": str(entry.path),
            "read_only": bool(entry.read_only),
        }
        for entry in window.workspace_roots.roots
    ]


def unique_root_name(base: str, taken: set[str]) -> str:
    name = (base or "project").strip() or "project"
    # Config keys should stay path-safe and qualifier-friendly.
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)
    cleaned = cleaned.strip("-_") or "project"
    if cleaned not in taken:
        return cleaned
    n = 2
    while f"{cleaned}-{n}" in taken:
        n += 1
    return f"{cleaned}-{n}"


def register_workspace_folder(window, path: Path, *, make_active: bool = True) -> None:
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        window.thinking.append(f"Could not resolve folder: {exc}", kind="status")
        return
    if not resolved.is_dir():
        window.thinking.append(f"Not a folder: {resolved}", kind="status")
        return
    for entry in window.workspace_roots.roots:
        if entry.path.resolve() == resolved:
            window.workspace_roots.set_active(entry.name)
            window.workspace.set_active_project(entry.name)
            window.thinking.append(
                f"Already a root — active project `{entry.name}`.",
                kind="status",
            )
            return
    taken = set(window.workspace_roots.names())
    name = unique_root_name(resolved.name, taken)
    roots = workspace_root_dicts(window)
    roots.append({"name": name, "path": str(resolved), "read_only": False})
    apply_workspace_roots(
        window, roots, preferred_active=name if make_active else None
    )


def add_workspace_folder_dialog(window) -> None:
    from PySide6.QtWidgets import QFileDialog

    start = str(Path.home() / "Documents")
    chosen = QFileDialog.getExistingDirectory(
        window, "Add folder to workspace", start
    )
    if chosen:
        register_workspace_folder(window, Path(chosen), make_active=True)


def new_workspace_folder_dialog(window) -> None:
    from PySide6.QtWidgets import QFileDialog, QInputDialog

    start = str(Path.home() / "Documents")
    parent = QFileDialog.getExistingDirectory(
        window, "Parent folder for new project", start
    )
    if not parent:
        return
    name, ok = QInputDialog.getText(window, "New folder", "Folder name:")
    if not ok:
        return
    folder_name = (name or "").strip()
    if not folder_name:
        window.thinking.append("Folder name required.", kind="status")
        return
    target = Path(parent) / folder_name
    try:
        target.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        window.thinking.append(f"Already exists: {target}", kind="status")
        return
    except OSError as exc:
        window.thinking.append(f"Could not create folder: {exc}", kind="status")
        return
    register_workspace_folder(window, target, make_active=True)


def remove_active_workspace_root(window) -> None:
    if len(window.workspace_roots) <= 1:
        window.thinking.append("Keep at least one workspace root.", kind="status")
        return
    active = window.workspace_roots.active
    roots = [r for r in workspace_root_dicts(window) if r["name"] != active]
    next_active = str(roots[0]["name"]) if roots else None
    apply_workspace_roots(window, roots, preferred_active=next_active)
    window.thinking.append(
        f"Removed `{active}` from the workspace (files untouched on disk).",
        kind="status",
    )


def open_file(window, path: str) -> None:
    if not path:
        window.chat.add_system(
            "open needs a path — pick a file or type one under the workspace roots"
        )
        return
    window._reveal_dock(window.work_dock, window.act_workspace)
    try:
        hit = window.workspace_roots.resolve_read(path)
    except Exception as exc:
        window.chat.add_system(f"I could not open that file. {plain_reason(exc)}")
        window.thinking.append(f"open failed: {exc!r}", kind="status")
        return
    if not hit.path.is_file():
        label = hit.qualified(multi=len(window.workspace_roots) > 1)
        window.chat.add_system(f"Not a file: {label}")
        return
    try:
        text = hit.path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        window.chat.add_system(f"I could not read that file. {plain_reason(exc)}")
        window.thinking.append(f"open failed: {exc!r}", kind="status")
        return
    label = hit.qualified(multi=len(window.workspace_roots) > 1)
    if window.workspace.has_unsaved_changes():
        # Opening a file replaces the buffer, so an open on top of unsaved
        # edits is a discard. It stays possible — it is what the operator
        # clicked — but it says so once first, since the edits are about to
        # be gone with no undo behind them.
        if window._workspace_discard_armed != str(hit.path):
            window._workspace_discard_armed = str(hit.path)
            window.chat.add_system(
                f"Unsaved changes in {window.workspace.loaded_label()}. "
                f"Save them first, or press open again to discard them and load {label}."
            )
            return
    window._workspace_discard_armed = ""
    window.workspace.set_file(
        label, text, root_name=hit.root_name, abs_path=str(hit.path), force=True
    )
    window.workspace.set_recent(push_recent_workspace_file(label))
    window.thinking.append(f"workspace open {label}", kind="status")


def disk_moved_under_editor(window, target: Path, content: str) -> bool:
    """True when target changed since the editor loaded it, and not to this text.

    Only the file the editor is actually holding can be stale — a save to
    any other path is a plain write with nothing to lose.
    """
    loaded = window.workspace.loaded_abs()
    if not loaded or str(target) != loaded or not target.is_file():
        return False
    try:
        on_disk = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return on_disk != window.workspace.baseline_text() and on_disk != content


def save_file(window, path: str, content: str) -> None:
    if not path:
        window.chat.add_system("save needs a path")
        return
    window._reveal_dock(window.work_dock, window.act_workspace)
    try:
        hit = window.workspace_roots.resolve(path, for_create=True, for_write=True)
    except Exception as exc:
        window.chat.add_system(f"I could not save there. {plain_reason(exc)}")
        window.thinking.append(f"save failed: {exc!r}", kind="status")
        return
    label = hit.qualified(multi=len(window.workspace_roots) > 1)
    if disk_moved_under_editor(window, hit.path, content):
        # The other half of the clobber: she edited the file after it was
        # opened, so this save carries a buffer that predates her work and
        # would drop it. Overwriting is allowed, once it is a decision.
        if window._workspace_overwrite_armed != str(hit.path):
            window._workspace_overwrite_armed = str(hit.path)
            window.chat.add_system(
                f"{label} changed on disk after you opened it — saving now would "
                "overwrite that version. Press save again to overwrite it, or open "
                "the file again to load what is on disk."
            )
            return
    window._workspace_overwrite_armed = ""
    try:
        hit.path.parent.mkdir(parents=True, exist_ok=True)
        hit.path.write_text(content, encoding="utf-8")
    except OSError as exc:
        window.chat.add_system(f"I could not save that file. {plain_reason(exc)}")
        window.thinking.append(f"save failed: {exc!r}", kind="status")
        return
    window.workspace.set_file(
        label, content, root_name=hit.root_name, abs_path=str(hit.path), force=True
    )
    window.workspace.set_recent(push_recent_workspace_file(label))
    record_artifact(
        window,
        str(hit.path),
        label=label,
        source="save",
        root_name=hit.root_name,
    )
    window.thinking.append(f"workspace saved {label}", kind="status")
    window.chat.add_system(f"Saved {label}")


def desk_store(window) -> DeskStore:
    store = getattr(window, "desk", None)
    if isinstance(store, DeskStore):
        return store
    store = DeskStore()
    window.desk = store
    return store


def refresh_desk(window) -> None:
    store = desk_store(window)
    room = window.conversation.room
    room_id = str(room.room_id or "")
    root_name = window.workspace_roots.active
    items = store.list_for(
        root_name=root_name,
        room_id=room_id,
        include_orbit=not room_id,
    )
    room_name = ""
    if room_id:
        room_name = str(room.name.text() or room_id)
    window.workspace.set_desk_context(room_id=room_id, room_name=room_name)
    window.workspace.set_desk_items(items)


def record_artifact(
    window,
    abs_path: str,
    *,
    label: str = "",
    kind: str = "",
    source: str = "open",
    root_name: str = "",
    pin: bool = False,
) -> None:
    store = desk_store(window)
    room_id = str(window.conversation.room.room_id or "")
    store.record(
        abs_path,
        label=label,
        kind=kind,
        source=source,
        root_name=root_name,
        room_id=room_id,
        pin=pin,
    )
    refresh_desk(window)


def keep_note_dialog(window) -> None:
    text = ask_text(
        window,
        "Keep a note",
        "This lands on the desk as a page in this project. Say it again later and she can find it.",
        placeholder="the spare key is under the planter",
        accept_text="Keep",
    )
    if not text:
        return
    room_id = str(window.conversation.room.room_id or "")
    try:
        item = write_note(
            window.workspace_roots, text, room_id=room_id, store=desk_store(window)
        )
    except Exception as exc:
        window.chat.add_system(f"I could not keep that. {plain_reason(exc)}")
        return
    window.workspace.show_desk()
    window._reveal_dock(window.work_dock, window.act_workspace)
    open_desk_item(window, item.abs_path)
    window.chat.add_system(f"On the desk: {item.label}")
    refresh_desk(window)


def pin_desk_item(window, abs_path: str, pinned: bool) -> None:
    desk_store(window).pin(abs_path, pinned=pinned)
    refresh_desk(window)


def drop_desk_item(window, abs_path: str) -> None:
    desk_store(window).drop(abs_path)
    refresh_desk(window)


def open_desk_item(window, abs_path: str) -> None:
    path = Path(abs_path)
    if not path.is_file():
        window.chat.add_system("That file is no longer on disk.")
        refresh_desk(window)
        return
    kind = infer_kind(path)
    window._reveal_dock(window.work_dock, window.act_workspace)
    window.workspace.show_desk()
    record_artifact(window, str(path), source="open")
    if is_image_kind(kind, str(path)):
        window.workspace.show_image(str(path))
        return
    if is_text_kind(kind, str(path)):
        open_file(window, str(path))
        return
    try:
        open_local_file(path)
    except OSError as exc:
        window.chat.add_system(f"I could not open {path.name}. {plain_reason(exc)}")


def reveal_desk_item(window, abs_path: str) -> None:
    try:
        reveal_local_file(abs_path)
    except OSError as exc:
        leaf = Path(abs_path).name or "that file"
        window.chat.add_system(f"I could not show {leaf}. {plain_reason(exc)}")


def open_outside(window, abs_path: str) -> None:
    try:
        open_local_file(abs_path)
    except OSError as exc:
        leaf = Path(abs_path).name or "that file"
        window.chat.add_system(f"I could not open {leaf}. {plain_reason(exc)}")


def bind_workspace(window) -> None:
    window.workspace.open_requested.connect(lambda path: open_file(window, path))
    window.workspace.save_requested.connect(
        lambda path, content: save_file(window, path, content)
    )
    window.workspace.add_root_requested.connect(
        lambda: add_workspace_folder_dialog(window)
    )
    window.workspace.new_root_requested.connect(
        lambda: new_workspace_folder_dialog(window)
    )
    window.workspace.remove_root_requested.connect(
        lambda: remove_active_workspace_root(window)
    )
    window.workspace.keep_requested.connect(lambda: keep_note_dialog(window))
    window.workspace.pin_requested.connect(
        lambda path, pinned: pin_desk_item(window, path, pinned)
    )
    window.workspace.drop_requested.connect(lambda path: drop_desk_item(window, path))
    window.workspace.desk_open_requested.connect(
        lambda path: open_desk_item(window, path)
    )
    window.workspace.reveal_requested.connect(
        lambda path: reveal_desk_item(window, path)
    )
    window.workspace.outside_requested.connect(lambda path: open_outside(window, path))

