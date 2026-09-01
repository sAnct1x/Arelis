"""Room talk and setup. Voice control stays on Orchestrator."""

from __future__ import annotations

from typing import Any

from arelis.core.events import Event, EventType
from arelis.rooms import (
    Room,
    RoomSetup,
    infer_kind,
    looks_like_room_name,
    match_room_project,
    match_set_kind_intent,
    match_set_purpose_intent,
    match_set_root_intent,
    match_skip_setup_intent,
    match_skip_step_intent,
    match_start_setup_intent,
    needs_setup,
    normalize_room_name,
    setup_prompt,
    strip_setup_value,
)
from arelis.spatial import PHYSICS_ROOM_ID


async def room_command(orch: Any, text: str) -> None:
    """`/room`, `/rooms`, and the four things you can do to one."""
    parts = text.split(maxsplit=2)
    verb = parts[1].strip().lower() if len(parts) > 1 else ""
    rest = parts[2].strip() if len(parts) > 2 else ""

    if not verb:
        await orch._say(rooms_overview(orch))
        return
    if verb == "new":
        await enter_or_create_room(orch, rest)
        return
    if verb == "set":
        message = set_room_field(orch, rest)
        # Repaint before answering. The strip shows the purpose and the
        # folder, so changing either without republishing leaves the banner
        # describing a room that no longer exists in that form — and the
        # banner is the only place either one is visible.
        room = orch.rooms.active
        if room is not None:
            await publish_room_only(orch, room)
        orch._room_setup = None
        await orch._say(message)
        return
    if verb == "forget":
        await orch._say(forget_room(orch, rest))
        return
    if verb in {"leave", "general"}:
        await leave_room(orch)
        return

    wanted = f"{verb} {rest}".strip()
    await enter_or_create_room(orch, wanted)


def rooms_overview(orch: Any) -> str:
    rooms = orch.rooms.all()
    if not rooms:
        return (
            "No rooms yet. A room is a named place to work on one thing — it "
            "keeps its own conversation, points at one project folder, and "
            "remembers what it is for.\n\n"
            "Make one by saying \"let's work on <name>\", or `/room new "
            "<name>`. She will ask what it is for in the chat."
        )
    active = orch.rooms.active_id
    lines = []
    for room in rooms:
        mark = " (open)" if room.id == active else ""
        detail = room.purpose or room.spec.blurb
        where = f" · `{room.root}`" if room.root else ""
        if room.name and room.name.lower() != room.id:
            ident = f"{room.name} (`{room.id}`)"
        else:
            ident = f"`{room.id}`"
        lines.append(f"- {ident}{mark} — {detail}{where}")
    body = "Rooms:\n" + "\n".join(lines)
    if active:
        body += "\n\nLeave with `/leave`."
    else:
        body += "\n\nEnter one with `/room <name>`."
    return body


async def enter_or_create_room(orch: Any, wanted: str) -> None:
    """`/room physics` and \"let's work on Reality\" are the same room.

    Find the room. Walk in. If there isn't one and the name is a room
    name, make it and walk in. Already inside: say so, do not start a turn.
    Earth is a zone inside Reality, not a room to create.
    """
    from arelis.rooms import PHYSICS_ALIASES

    name = normalize_room_name(wanted)
    if not name:
        await orch._say(
            "Name it: `/room physics`, or say \"let's work on Reality\"."
        )
        return
    folded = name.lower()
    if folded == "earth":
        await orch._say(
            "Earth is a zone inside Reality, not a room. "
            "Say \"let's work on Reality\", then enter Earth."
        )
        return
    room = orch.rooms.find(name)
    created = False
    if room is None:
        if folded in PHYSICS_ALIASES:
            room = orch.rooms.get(PHYSICS_ROOM_ID)
        if room is None and not looks_like_room_name(name):
            await orch._say(
                f"No room called `{name}`. "
                f"Make one with `/room new {name}`, or `/rooms` to see what exists."
            )
            return
        if room is None:
            display = name if any(ch.isupper() for ch in name) else name.title()
            try:
                room = orch.rooms.create(display)
            except ValueError as exc:
                await orch._say(str(exc))
                return
            created = True
    if room is None:
        await orch._say(f"No room called `{name}`.")
        return
    if room.id == orch.rooms.active_id:
        await offer_reality_plate(orch, room)
        if needs_setup(room) and orch._room_setup is None:
            await begin_room_setup(orch, room)
            return
        await orch._say(f"Already in {room.name}.")
        return
    preamble = ""
    if created:
        preamble = f"Made the `{room.id}` room and opened it."
    setup_ask = ""
    if needs_setup(room):
        setup_ask = setup_prompt("purpose", room, orch.workspace.names())
    await enter_room(orch, room, preamble=preamble, extra=setup_ask)
    await offer_reality_plate(orch, room)
    live = orch.rooms.get(room.id) or room
    if setup_ask:
        await begin_room_setup(orch, live, announce=False)


async def offer_reality_plate(orch: Any, room: Room) -> None:
    """Open Reality's plate when the stage is granted. One room, one thread."""
    if room.id != PHYSICS_ROOM_ID:
        return
    await orch.bus.publish(
        Event(
            EventType.PHYSICS_VERB,
            {"verb": "lab", "on": True, "text": "open Reality"},
        )
    )


async def handle_room_talk(orch: Any, text: str) -> bool:
    """Closed room setup and spoken field edits. True = no model turn."""
    room = orch.rooms.active
    if match_start_setup_intent(text):
        if room is None:
            await orch._say(
                "No room is open. Say \"let's work on\" a name first."
            )
            return True
        await begin_room_setup(orch, room, restart=True)
        return True
    if orch._room_setup is not None:
        if room is None or room.id != orch._room_setup.room_id:
            orch._room_setup = None
        elif match_skip_setup_intent(text):
            await finish_room_setup(orch, skipped=True, user_text=text)
            return True
        elif match_skip_step_intent(text):
            await advance_room_setup(orch, user_text=text)
            return True
        elif await take_setup_answer(orch, text):
            return True
    if room is None:
        return False
    purpose = match_set_purpose_intent(text)
    if purpose:
        await apply_room_fields(orch, {"purpose": purpose}, user_text=text)
        return True
    root = match_set_root_intent(text, orch.workspace.names())
    if root:
        await apply_room_fields(orch, {"root": root}, user_text=text)
        return True
    kind = match_set_kind_intent(text)
    if kind:
        await apply_room_fields(orch, {"kind": kind}, user_text=text)
        return True
    return False


async def begin_room_setup(
    orch: Any, room: Room, *, restart: bool = False, announce: bool = True
) -> None:
    orch._room_setup = RoomSetup(room.id, "purpose")
    if restart and room.setup:
        try:
            orch.rooms.update(room.id, setup="")
        except ValueError:
            pass
    prompt = setup_prompt(orch._room_setup.step, room, orch.workspace.names())
    orch.memory.add("assistant", prompt)
    if announce:
        await orch._say(prompt, status=False)


async def take_setup_answer(orch: Any, text: str) -> bool:
    setup = orch._room_setup
    room = orch.rooms.active
    if setup is None or room is None:
        return False
    step = setup.step
    if step == "root":
        root = match_room_project(text, orch.workspace.names())
        if root is None:
            names = orch.workspace.names()
            listed = ", ".join(f"`{item}`" for item in names) or "none yet"
            reply = (
                f"I don't have a project called that. Existing: {listed}. "
                "Say the name, or skip."
            )
            orch.memory.add("user", text)
            orch.memory.add("assistant", reply)
            await orch._say(reply)
            return True
        await apply_room_fields(orch, {"root": root}, user_text=text, quiet=True)
        await advance_room_setup(orch)
        return True
    value = strip_setup_value(step, text)
    if not value:
        return False
    await apply_room_fields(orch, {step: value}, user_text=text, quiet=True)
    await advance_room_setup(orch)
    return True


async def advance_room_setup(orch: Any, *, user_text: str = "") -> None:
    setup = orch._room_setup
    if setup is None:
        return
    nxt = setup.advance()
    room = orch.rooms.active
    if nxt is None or room is None:
        await finish_room_setup(orch, skipped=False, user_text=user_text)
        return
    orch._room_setup = nxt
    if user_text:
        orch.memory.add("user", user_text)
    prompt = setup_prompt(nxt.step, room, orch.workspace.names())
    orch.memory.add("assistant", prompt)
    await orch._say(prompt, status=False)


async def finish_room_setup(
    orch: Any, *, skipped: bool, user_text: str = ""
) -> None:
    room = orch.rooms.active
    orch._room_setup = None
    if room is None:
        return
    live = orch.rooms.get(room.id) or room
    fields: dict[str, Any] = {"setup": "skipped" if skipped else "done"}
    if not skipped and live.kind == "general":
        guessed = infer_kind(live.purpose, live.result)
        if guessed != live.kind:
            fields["kind"] = guessed
    await apply_room_fields(orch, fields, user_text=user_text, quiet=True)
    updated = orch.rooms.get(room.id) or live
    message = setup_closing(orch, updated, skipped)
    orch.memory.add("assistant", message)
    await orch._say(message)


def setup_closing(orch: Any, room: Room, skipped: bool) -> str:
    if skipped:
        return (
            f"{room.name} can wait. Say \"set up this room\" when you want "
            "the questions, or just talk."
        )
    bits = [f"{room.name} is set."]
    if room.purpose:
        bits.append(room.purpose)
    if room.root:
        bits.append(f"Working in `{room.root}`.")
    if room.result:
        bits.append(f"Done looks like: {room.result}")
    if room.test:
        bits.append(f"A run counts when: {room.test}")
    bits.append(f"I'll lean {room.kind}.")
    return " ".join(bits)


async def apply_room_fields(
    orch: Any,
    fields: dict[str, Any],
    *,
    user_text: str = "",
    quiet: bool = False,
    closing: str = "",
) -> None:
    room = orch.rooms.active
    if room is None:
        await orch._say("No room is open.")
        return
    if "root" in fields and fields["root"] not in orch.workspace.names():
        await orch._say(
            f"No project called `{fields['root']}`. Existing: "
            + ", ".join(f"`{n}`" for n in orch.workspace.names())
            + ". Add a folder in the workspace dock first."
        )
        return
    try:
        updated = orch.rooms.update(room.id, **fields)
    except ValueError as exc:
        await orch._say(str(exc))
        return
    if "root" in fields:
        point_workspace_at(orch, updated)
    if "kind" in fields and updated.role is not None:
        orch.router.default_role = updated.role  # type: ignore[assignment]
    await publish_room_only(orch, updated)
    message = closing or field_ack(orch, updated, fields)
    if user_text:
        orch.memory.add("user", user_text)
    orch.memory.add("assistant", message)
    if not quiet or closing:
        await orch._say(message)


def field_ack(orch: Any, room: Room, fields: dict[str, Any]) -> str:
    shown = {key: fields[key] for key in fields if key != "setup"}
    if not shown:
        return f"{room.name} is updated."
    if len(shown) == 1:
        key, value = next(iter(shown.items()))
        return f"{room.name}: {key} is {value}."
    return f"{room.name} is updated."


def set_room_field(orch: Any, rest: str) -> str:
    room = orch.rooms.active
    if room is None:
        return "No room is open. `/room <name>` first, or `/rooms` to see them."
    parts = rest.split(maxsplit=1)
    field = parts[0].strip().lower() if parts else ""
    value = parts[1].strip() if len(parts) > 1 else ""
    if field not in {"purpose", "root", "kind", "name", "result", "test"}:
        return (
            "Set `purpose`, `root`, `kind`, `name`, `result` or `test`. "
            "For example: `/room set purpose analysing the survey data`."
        )
    if not value:
        return f"Give it a value: `/room set {field} …`."
    if field == "root" and value not in orch.workspace.names():
        return (
            f"No project called `{value}`. Existing: "
            + ", ".join(f"`{n}`" for n in orch.workspace.names())
            + ". Add a folder in the workspace dock first."
        )
    try:
        updated = orch.rooms.update(room.id, **{field: value})
    except ValueError as exc:
        return str(exc)
    if field == "root":
        point_workspace_at(orch, updated)
    if field == "kind" and updated.role is not None:
        # Entering a room applies its lean, so setting the kind from inside
        # one would otherwise do nothing until you left and came back —
        # which reads as the command having been ignored.
        orch.router.default_role = updated.role  # type: ignore[assignment]
    return f"`{updated.id}`: {field} set to {value}."


def forget_room(orch: Any, rest: str) -> str:
    wanted = rest.strip()
    room = orch.rooms.find(wanted) if wanted else orch.rooms.active
    if room is None:
        return f"No room called `{wanted}`." if wanted else "No room is open."
    try:
        orch.rooms.remove(room.id)
    except ValueError as exc:
        return str(exc)
    return (
        f"Forgot the `{room.id}` room. Its conversations are still in History "
        "— only the room itself is gone."
    )


def point_workspace_at(orch: Any, room: Room) -> str:
    """Make the room's folder active. Returns a note if it could not be."""
    if not room.root:
        return ""
    try:
        orch.workspace.set_active(room.root)
    except ValueError:
        return (
            f" Its folder `{room.root}` is not a project any more, so paths "
            "still resolve against "
            f"`{orch.workspace.active}`."
        )
    return ""


async def resume_last_room(orch: Any) -> bool:
    """Open the room this process last left in, if it still exists.

    Does not create a room. Orbit if they left, or if the room was forgotten.
    Silent: the strip and the thread are the proof, not a launch speech.
    """
    wanted = orch.rooms.last_active_id
    room = orch.rooms.get(wanted) if wanted else None
    if room is None:
        return False
    await enter_room(orch, room, silent=True, fresh=True)
    return True


async def enter_room(
    orch: Any,
    room: Room,
    *,
    preamble: str = "",
    extra: str = "",
    silent: bool = False,
    fresh: bool = False,
) -> None:
    """Open a room: its thread, its folder, its role — all three at once.

    Refused mid-turn for the same reason a session load is: the running turn
    owns SessionMemory, and swapping the thread underneath it would answer
    one conversation into another.
    """
    task = orch._turn_task
    if task is not None and not task.done():
        await orch._say("Finish or stop the current turn first.")
        return
    store = orch._memory_store()
    if store is None:
        await orch._say("Rooms need the conversation archive, which is not available.")
        return

    if orch.rooms.active is None and store.session_id:
        parked = store.session_id
        if fresh and not store._session_has_messages(parked):
            store.delete_session(parked)
        else:
            orch._general_session = parked

    rows: list[dict[str, Any]] = []
    summary = ""
    if fresh:
        session_id = store.start_or_reuse_empty_session(room_id=room.id)
    else:
        session_id = store.latest_session_id(room_id=room.id, require_messages=False)
        if session_id is None or not store.open_session(session_id):
            session_id = store.start_session(room_id=room.id)
        else:
            rows = store.get_messages(session_id)
            summary = store.get_summary(session_id)
    orch.memory.hydrate(rows, summary=summary)
    orch.rooms.set_active(room.id)

    note = point_workspace_at(orch, room)
    if room.role is not None:
        orch.router.default_role = room.role  # type: ignore[assignment]

    await publish_room(orch, room, session_id, rows, summary)
    if silent:
        return
    opened = "Picking up where we left off." if rows else "New thread."
    lines = [preamble] if preamble else [f"In {room.name}. {opened}"]
    if extra:
        lines.append(extra)
    if room.purpose:
        lines.append(room.purpose)
    where = []
    if room.root:
        where.append(f"working in `{room.root}`")
    if room.role:
        where.append(f"`{room.role}` model")
    if where:
        # Only the first letter. str.capitalize() lowercases the rest, which
        # turned the project `Arelis Source` into `arelis source` in the one
        # line whose job is telling you which folder she is about to write to.
        sentence = " · ".join(where)
        lines.append(sentence[0].upper() + sentence[1:] + ".")
    if note:
        lines.append(note.strip())
    await orch._say(
        "\n\n".join(part for part in lines if part),
        status=False,
    )


async def leave_room(orch: Any) -> None:
    """Back to the general conversation, and the thread it was on."""
    room = orch.rooms.active
    if room is None:
        await orch._say("No room is open.")
        return
    task = orch._turn_task
    if task is not None and not task.done():
        await orch._say("Finish or stop the current turn first.")
        return
    store = orch._memory_store()
    if store is None:
        await orch._say("Rooms need the conversation archive, which is not available.")
        return

    orch.rooms.leave()
    orch._room_setup = None
    rows: list[dict[str, Any]] = []
    summary = ""
    target = orch._general_session or store.latest_session_id(
        room_id="", require_messages=True
    )
    if target and store.open_session(target):
        rows = store.get_messages(target)
        summary = store.get_summary(target)
    else:
        target = store.start_session()
    orch.memory.hydrate(rows, summary=summary)
    orch._general_session = ""

    await publish_room(orch, None, target, rows, summary)
    await orch._say(f"Out of {room.name}. Back to the general conversation.")


async def publish_room_only(orch: Any, room: Room) -> None:
    """The room's details changed, but the thread did not.

    Separate from publish_room because that one is followed by
    SESSION_LOADED, and repainting the transcript after `/room set purpose`
    would scroll the conversation to the top for a one-word edit.
    """
    await orch.bus.publish(
        Event(
            EventType.ROOM_CHANGED,
            {
                "room_id": room.id,
                "name": room.name,
                "purpose": room.purpose,
                "root": room.root,
                "kind": room.kind,
                "session_id": orch._memory_store().session_id
                if orch._memory_store() is not None
                else "",
            },
        )
    )


async def publish_room(
    orch: Any,
    room: Room | None,
    session_id: str,
    rows: list[dict[str, Any]],
    summary: str,
) -> None:
    """Tell the surfaces the thread moved, then hand them the messages.

    Order matters: ROOM_CHANGED first so the chat knows which room it is
    painting before the transcript lands in it.
    """
    await orch.bus.publish(
        Event(
            EventType.ROOM_CHANGED,
            {
                "room_id": room.id if room else "",
                "name": room.name if room else "",
                "purpose": room.purpose if room else "",
                "root": room.root if room else "",
                "kind": room.kind if room else "",
                "session_id": session_id,
            },
        )
    )
    await orch.bus.publish(
        Event(
            EventType.SESSION_LOADED,
            {
                "ok": True,
                "session_id": session_id,
                "messages": [
                    {
                        "role": row["role"],
                        "content": row["content"],
                        "note": row.get("note") or "",
                    }
                    for row in rows
                ],
                "summary": summary,
                "room_id": room.id if room else "",
            },
        )
    )
