"""Make and describe rooms from a sentence, through the confirm gate.

The slash commands are exact and the operator has to know them. This is the
other half: "make me a survey room that works in my Interferometer folder for
analysing fringe data" should end with that room existing, configured, without
anybody spelling `/room set purpose`.

Entering a room is deliberately not here. A room swap replaces the conversation
thread, and this tool runs *inside* a turn that is using that thread — swapping
it mid-turn would answer one conversation into another. So the tool builds the
room and says how to walk into it; the orchestrator owns the walking.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arelis.rooms import KINDS, RoomStore
from arelis.tools.base import ToolResult

WRITE_ACTIONS = frozenset({"create", "update", "forget"})


class RoomsTool:
    name = "rooms"
    description = (
        "List, create, or reconfigure rooms. A room is a named place to work on "
        "one long-running thing: it keeps its own conversation thread, points at "
        "one workspace project, and carries a purpose that is given to you every "
        "turn inside it. Use create when the user asks for a room or a dedicated "
        "space for a project, and fill purpose and root from what they said "
        "rather than asking twice. You cannot enter a room from here — tell the "
        "user to say \"let's work on <name>\" or type /room <name>. Creating and "
        "changing rooms is confirmed by the user first."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get", "create", "update", "forget"],
                "description": (
                    "list every room, get one, create a new one, update an "
                    "existing one, or forget one (its conversations are kept)"
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "Room name, as the user would say it — 'Reality'. Required "
                    "for create; identifies the room for get/update/forget."
                ),
            },
            "purpose": {
                "type": "string",
                "description": (
                    "One or two sentences on what this room is for, written to "
                    "be read by you at the start of every turn in it. Say what "
                    "the work is and what a good answer looks like."
                ),
            },
            "root": {
                "type": "string",
                "description": (
                    "Name of the workspace project this room works in. Must "
                    "already exist — call workspace or ask the user if unsure."
                ),
            },
            "kind": {
                "type": "string",
                "enum": sorted(KINDS),
                "description": (
                    "The lean: which model and skills to reach for first. "
                    + " ".join(f"{k}: {v.blurb}" for k, v in sorted(KINDS.items()))
                ),
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: RoomStore | None = None, path: Path | None = None) -> None:
        self._store = store
        self._path = path

    @property
    def store(self) -> RoomStore:
        """Resolved late so the tool shares the orchestrator's store.

        Built at registry time the tool would hold its own copy, and a room
        created here would not exist for the command that enters it until
        something reloaded the file.
        """
        if self._store is None:
            self._store = RoomStore(self._path)
        return self._store

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        name = str(kwargs.get("name") or "").strip()
        if action == "list":
            return self._list()
        if action == "get":
            return self._get(name)
        if action == "create":
            return self._create(kwargs)
        if action == "update":
            return self._update(kwargs)
        if action == "forget":
            return self._forget(name)
        return ToolResult(
            ok=False,
            output="Unknown action. Use list, get, create, update, or forget.",
        )

    def _describe(self, room: Any) -> str:
        bits = [f"`{room.id}` — {room.name}"]
        if room.purpose:
            bits.append(f"  purpose: {room.purpose}")
        if room.root:
            bits.append(f"  project: {room.root}")
        bits.append(f"  kind: {room.kind} ({room.spec.blurb})")
        if room.tools:
            bits.append(f"  limited to tools: {', '.join(room.tools)}")
        return "\n".join(bits)

    def _list(self) -> ToolResult:
        rooms = self.store.all()
        if not rooms:
            return ToolResult(
                ok=True,
                output=(
                    "No rooms yet. Create one with action=create when the user "
                    "wants a dedicated space for an ongoing piece of work."
                ),
                data={"rooms": []},
            )
        active = self.store.active_id
        body = "\n\n".join(self._describe(r) for r in rooms)
        return ToolResult(
            ok=True,
            output=f"{body}\n\n{len(rooms)} room(s). Open now: {active or 'none'}.",
            data={
                "rooms": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "purpose": r.purpose,
                        "root": r.root,
                        "kind": r.kind,
                    }
                    for r in rooms
                ],
                "active": active,
            },
        )

    def _get(self, name: str) -> ToolResult:
        room = self.store.find(name) if name else self.store.active
        if room is None:
            return ToolResult(
                ok=False,
                output=(
                    f"No room matching {name!r}."
                    if name
                    else "No room is open, and no name was given."
                ),
            )
        return ToolResult(ok=True, output=self._describe(room), data={"id": room.id})

    def _create(self, kwargs: dict[str, Any]) -> ToolResult:
        name = str(kwargs.get("name") or "").strip()
        if not name:
            return ToolResult(
                ok=False,
                output="A room needs a name. Ask the user what to call it.",
            )
        kind = str(kwargs.get("kind") or "").strip().lower() or "general"
        if kind not in KINDS:
            return ToolResult(
                ok=False,
                output=f"Unknown kind {kind!r}. Use one of: {', '.join(sorted(KINDS))}.",
            )
        try:
            room = self.store.create(
                name,
                purpose=str(kwargs.get("purpose") or "").strip(),
                root=str(kwargs.get("root") or "").strip(),
                kind=kind,
            )
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        return ToolResult(
            ok=True,
            output=(
                f"Created the room.\n\n{self._describe(room)}\n\n"
                f"Tell the user they can go in by saying \"let's work on "
                f"{room.name}\" or typing `/room {room.id}`."
            ),
            data={"id": room.id, "name": room.name},
        )

    def _update(self, kwargs: dict[str, Any]) -> ToolResult:
        name = str(kwargs.get("name") or "").strip()
        room = self.store.find(name) if name else self.store.active
        if room is None:
            return ToolResult(
                ok=False,
                output=(
                    f"No room matching {name!r}."
                    if name
                    else "No room is open, so there is nothing to update."
                ),
            )
        fields: dict[str, Any] = {}
        for key in ("purpose", "root", "kind"):
            value = str(kwargs.get(key) or "").strip()
            if value:
                fields[key] = value.lower() if key == "kind" else value
        if not fields:
            return ToolResult(
                ok=False,
                output="Nothing to change. Pass purpose, root or kind.",
            )
        try:
            updated = self.store.update(room.id, **fields)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        return ToolResult(
            ok=True,
            output=f"Updated.\n\n{self._describe(updated)}",
            data={"id": updated.id},
        )

    def _forget(self, name: str) -> ToolResult:
        room = self.store.find(name) if name else self.store.active
        if room is None:
            return ToolResult(ok=False, output=f"No room matching {name!r}.")
        try:
            self.store.remove(room.id)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        return ToolResult(
            ok=True,
            output=(
                f"Forgot the `{room.id}` room. Its conversations are still in "
                "History — only the room definition is gone."
            ),
            data={"id": room.id},
        )
