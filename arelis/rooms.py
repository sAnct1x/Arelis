"""Rooms: a named place to work on one thing, with its own thread.

The general conversation is deliberately ephemeral — cold launch opens an empty
orbit and last night stays in History. That is right for "what's the weather"
and wrong for "we have been building an interferometry analysis for three
weeks". Those need somewhere that remembers, that already knows which folder
the work lives in, and that does not have to be re-explained every launch.

A room is that place. It carries a thread, a folder, a lean, and a
purpose. The first time you walk into an empty one she asks for those
in the chat — typed or spoken, same path — and writes what you said.
Slash commands still work. You can also say the fields later.

What a room deliberately does *not* do is take capability away. The obvious
design is an allowlist per room, and it is wrong by default: ask her the time
in Reality and a caged agent has to say no, which teaches you to stop
asking. Rooms lean, they do not cage. A room that genuinely needs a cage can
set `tools:` explicitly, and then it is a decision somebody made rather than a
side effect of naming a folder.

Definitions live in data/rooms.yaml so they are readable and editable by hand,
matching contacts.yaml. The last room you *entered* is stored as last_active
and resumed on launch (the strip names it). Leaving writes an empty last_active,
so orbit stays orbit. Creating a room does not enter it. A forgotten room is
not recreated, except the permanent ones: they are seeded if missing and
cannot be forgotten.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from arelis.paths import state_dir

log = logging.getLogger(__name__)

ROOMS_PATH = state_dir() / "rooms.yaml"

# Reserved because they name the absence of a room in commands and events.
_RESERVED_IDS = frozenset({"", "general", "none", "new", "list", "leave", "help"})

# Same id as arelis.spatial.PHYSICS_ROOM_ID. Literal so this module does
# not depend on the spatial package — installed copies still get the room.
# Humans read Reality. The slash id stays physics so grants and tests
# do not fork. Spoken "Reality" resolves here; it is not a second room.
PHYSICS_ROOM_ID = "physics"
PHYSICS_DISPLAY_NAME = "Reality"
PHYSICS_ALIASES = frozenset(
    {"physics", "reality", "world", "solar-lab", "solar-system"}
)

PHYSICS_PURPOSE = (
    "Reality. True-scale solar system — JPL Horizons ICs, REBOUND, the laws "
    "as they are. Approach and orbit. No landing. Hands drive the camera, "
    "not metres in the ODE. Forces and periods come from the engine; you do "
    "not invent them. Earth is a zone on that globe, not another room. "
    "Leave ends the motion grant. Record takes in this project's folder, "
    "not in orbit."
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


# Spoken ways into a room. Same contract as `/room <name>`: resolve, enter
# if it exists, create if the name is short enough to be a room and not a
# topic. Fillers ("some", "the") are not part of the name.
_ENTER_INTENT = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        (?:let'?s|lets|i\s+want\s+to|can\s+we)\s+ (?:work|start\s+work)\s+ (?:on|in)\s+
      | (?:open|enter|go\s+to|switch\s+to|jump\s+(?:in)?to|work\s+in)\s+
    )
    (?:(?:the|some|an?)\s+)?
    (?P<name>.+?)
    (?:\s+room)?
    \s*[.!?]?\s*$
    """
)

# `/room new physics` said out loud. Long "make me a room for …" asks stay
# with the rooms tool so purpose and folder can still be filled in.
_MAKE_ROOM_INTENT = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:make|create|set\s+up)
    (?:\s+me)?
    (?:\s+(?:a|an|the))?
    (?:\s+new)?
    \s+
    (?:
        room\s+ (?:called|named)\s+ (?P<called>.+?)
      | (?P<named>[\w][\w\s-]{0,40}?)\s+room
    )
    \s*[.!?]?\s*$
    """
)

_LIST_ROOMS_INTENT = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        (?:list|show)\s+(?:the\s+)?rooms
      | what\s+rooms\s+(?:do\s+we\s+have|are\s+there|exist)
    )
    \s*[.!?]?\s*$
    """
)

_NAME_FILLERS = re.compile(r"^(?:some|a|an|the)\s+", re.IGNORECASE)
_TRAILING_ROOM = re.compile(r"\s+room$", re.IGNORECASE)
_TOPIC_MARKERS = re.compile(
    r"\b(?:of|for|about|that|which|with|from|when|how)\b",
    re.IGNORECASE,
)

_LEAVE_INTENT = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        (?:leave|exit|close|quit)\s+ (?:the\s+)? (?:room|this\s+room)
      | (?:back|go\s+back|return)\s+to\s+ (?:the\s+)? (?:general|normal|main)
        (?:\s+(?:chat|conversation))?
    )
    \s*[.!?]?\s*$
    """
)


def normalize_room_name(name: str) -> str:
    """'some physics', 'the Reality room' → 'physics' / 'Reality'."""
    cleaned = _clean(name)
    while True:
        stripped = _clean(_NAME_FILLERS.sub("", cleaned))
        if stripped == cleaned:
            break
        cleaned = stripped
    return _clean(_TRAILING_ROOM.sub("", cleaned))


def looks_like_room_name(name: str) -> bool:
    """True when this is a room to open, not a topic sentence or a file."""
    cleaned = normalize_room_name(name)
    if not cleaned or len(cleaned) > 48:
        return False
    if len(cleaned.split()) > 4:
        return False
    if _TOPIC_MARKERS.search(cleaned):
        return False
    if re.match(r"(?i)file\b", cleaned):
        return False
    if any(mark in cleaned for mark in (".", "/", "\\")):
        return False
    return True


def match_enter_intent(text: str) -> str | None:
    """The room name someone said, or None. Same as `/room <name>`."""
    found = _ENTER_INTENT.match(text or "")
    if found is None:
        return None
    name = normalize_room_name(found.group("name"))
    if not name:
        return None
    if re.match(r"(?i)file\b", name) or any(mark in name for mark in (".", "/", "\\")):
        return None
    if _TOPIC_MARKERS.search(name):
        return None
    return name


_NOT_A_NEW_ROOM = frozenset({"this", "that", "the", "our", "my", "current", "new"})


def match_make_room_intent(text: str) -> str | None:
    """`/room new <name>` said out loud, or None.

    "Set up this room" is configuring the open room, not creating `this`.
    """
    found = _MAKE_ROOM_INTENT.match(text or "")
    if found is None:
        return None
    name = normalize_room_name(found.group("called") or found.group("named") or "")
    if name.lower() in _NOT_A_NEW_ROOM:
        return None
    # "make it a research room" is a lean, not a room called "it a research".
    if match_set_kind_intent(text):
        return None
    return name if name and looks_like_room_name(name) else None


def match_list_rooms_intent(text: str) -> bool:
    return _LIST_ROOMS_INTENT.match(text or "") is not None


def match_leave_intent(text: str) -> bool:
    return _LEAVE_INTENT.match(text or "") is not None


_SKIP_SETUP = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        skip\s+(?:the\s+)?setup
      | later
      | not\s+now
      | (?:i(?:'ll| will)\s+)? (?:set\s+this\s+up|do\s+(?:this|it))\s+later
    )
    \s*[.!]?\s*$
    """
)
_SKIP_STEP = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        skip(?:\s+(?:this|it|that))?
      | none
      | no\s+(?:folder|project|root)
      | no\s+thanks
    )
    \s*[.!]?\s*$
    """
)
_START_SETUP = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        set\s+up\s+(?:this|the|our)\s+room
      | configure\s+(?:this|the)\s+room
    )
    \s*[.!]?\s*$
    """
)
_SET_PURPOSE = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        (?:this\s+room|it)\s+is\s+for
      | the\s+purpose\s+is
      | it'?s\s+for
    )
    \s+(?P<value>.+?)
    \s*[.!]?\s*$
    """
)
_SET_ROOT = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        work\s+in
      | use(?:\s+the)?
      | the\s+folder\s+is
      | the\s+project\s+is
      | point\s+(?:it\s+)?at
    )
    \s+(?P<value>.+?)
    \s*[.!]?\s*$
    """
)
_SET_KIND = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        kind\s+(?P<kind>\w+)
      | make\s+it\s+(?:an?\s+)?(?P<make>\w+)\s+room
      | this\s+is\s+(?:an?\s+)?(?P<this>\w+)\s+room
      | lean\s+(?P<lean>\w+)
    )
    \s*[.!]?\s*$
    """
)
_PURPOSE_LEAD = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        (?:this\s+room|it)\s+is\s+for
      | the\s+purpose\s+is
      | it'?s\s+for
    )
    \s+
    """
)
_RESULT_LEAD = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        (?:a\s+finished\s+)?result(?:\s+looks\s+like)?
      | done\s+(?:looks\s+like|is)
    )
    \s*(?:is|:)?\s+
    """
)
_TEST_LEAD = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:
        (?:a\s+)?run\s+counts\s+when
      | we\s+know\s+it\s+ran\s+when
      | the\s+test\s+is
    )
    \s+
    """
)
_FOLDER_TRAIL = re.compile(
    r"(?i)\s+(?:folder|project|root)$"
)
_KIND_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("code", ("pytest", "unit test", "refactor", "codebase", "pull request")),
    (
        "writing",
        ("draft", "essay", "write-up", "write up", "manuscript", "write the"),
    ),
    ("research", ("paper", "literature", "arxiv", "cite", "review the")),
    (
        "analysis",
        ("data", "plot", "csv", "survey", "catalog", "spreadsheet", "table"),
    ),
)

SETUP_STEPS: tuple[str, ...] = ("purpose", "root", "result", "test")


@dataclass(frozen=True)
class RoomSetup:
    """In-process first-entry interview. Not written to rooms.yaml mid-way."""

    room_id: str
    step: str

    def advance(self) -> RoomSetup | None:
        try:
            index = SETUP_STEPS.index(self.step)
        except ValueError:
            return None
        if index + 1 >= len(SETUP_STEPS):
            return None
        return RoomSetup(self.room_id, SETUP_STEPS[index + 1])


def needs_setup(room: Room) -> bool:
    """Empty new rooms only. Reality already has a contract."""
    if room.id == PHYSICS_ROOM_ID:
        return False
    if room.setup in {"done", "skipped"}:
        return False
    return not bool(room.purpose.strip())


def match_skip_setup_intent(text: str) -> bool:
    return _SKIP_SETUP.match(text or "") is not None


def match_skip_step_intent(text: str) -> bool:
    return _SKIP_STEP.match(text or "") is not None


def match_start_setup_intent(text: str) -> bool:
    return _START_SETUP.match(text or "") is not None


def match_set_purpose_intent(text: str) -> str | None:
    found = _SET_PURPOSE.match(text or "")
    if found is None:
        return None
    value = _clean(found.group("value"))
    return value or None


def match_set_kind_intent(text: str) -> str | None:
    found = _SET_KIND.match(text or "")
    if found is None:
        return None
    kind = (
        found.group("kind")
        or found.group("make")
        or found.group("this")
        or found.group("lean")
        or ""
    ).strip().lower()
    return kind if kind in KINDS else None


def match_room_project(text: str, names: Iterable[str]) -> str | None:
    """Resolve a spoken folder to one workspace project, or None."""
    raw = _FOLDER_TRAIL.sub("", _clean(text))
    raw = re.sub(
        r"(?i)^(work\s+in|use(?:\s+the)?|the\s+folder\s+is|the\s+project\s+is|"
        r"point\s+(?:it\s+)?at)\s+",
        "",
        raw,
    )
    raw = _FOLDER_TRAIL.sub("", _clean(raw))
    if not raw:
        return None
    known = [name for name in names if name]
    lowered = raw.lower()
    exact = [name for name in known if name.lower() == lowered]
    if len(exact) == 1:
        return exact[0]
    prefix = [name for name in known if name.lower().startswith(lowered)]
    if len(prefix) == 1:
        return prefix[0]
    inside = [name for name in known if lowered in name.lower() or name.lower() in lowered]
    if len(inside) == 1:
        return inside[0]
    return None


def match_set_root_intent(text: str, names: Iterable[str]) -> str | None:
    found = _SET_ROOT.match(text or "")
    if found is None:
        return None
    return match_room_project(found.group("value"), names)


def strip_setup_value(step: str, text: str) -> str:
    raw = _clean(text)
    if step == "purpose":
        raw = _clean(_PURPOSE_LEAD.sub("", raw))
    elif step == "result":
        raw = _clean(_RESULT_LEAD.sub("", raw))
    elif step == "test":
        raw = _clean(_TEST_LEAD.sub("", raw))
    return raw


def infer_kind(*texts: str) -> str:
    blob = " ".join(part for part in texts if part).lower()
    for kind, hints in _KIND_HINTS:
        if any(hint in blob for hint in hints):
            return kind
    return DEFAULT_KIND


def setup_prompt(step: str, room: Room, projects: Iterable[str]) -> str:
    name = room.name
    if step == "purpose":
        return (
            f"What is {name} for? One sentence is enough. "
            "Or say skip, or later to do this another time."
        )
    if step == "root":
        names = list(projects)
        if names:
            listed = ", ".join(f"`{item}`" for item in names)
            return (
                f"Which folder should the work live in? {listed}. "
                "Say the name, or skip."
            )
        return (
            "Which folder should the work live in? Add one in the workspace "
            "dock first, or say skip."
        )
    if step == "result":
        return (
            "What does a finished result look like — a plot, a dump, a table, "
            "two sentences in documents/? Or say skip."
        )
    if step == "test":
        return (
            "How will we know a run actually happened? "
            "Or say skip."
        )
    return ""


@dataclass(frozen=True)
class RoomKind:
    """A lean, not a cage.

    Role is a starting chip. Skills keep those tools in reach on every
    turn; they do not force a tool plan. Asking what a toroid is in an
    analysis room is still a conversation.
    """

    id: str
    label: str
    role: str | None
    skills: tuple[str, ...]
    blurb: str


# Roles must be members of arelis.llm.router.ROLES; skills are SKILL_CARDS ids.
KINDS: dict[str, RoomKind] = {
    "general": RoomKind(
        id="general",
        label="General",
        role=None,
        skills=(),
        blurb="No lean. Whatever the work turns out to be.",
    ),
    "code": RoomKind(
        id="code",
        label="Code",
        role="fast",
        skills=("workspace", "code"),
        blurb="Reading and writing files in the project, running the tests.",
    ),
    "research": RoomKind(
        id="research",
        label="Research",
        role="research",
        skills=("web", "workspace"),
        blurb="Reading widely, keeping notes, citing what it found.",
    ),
    "analysis": RoomKind(
        id="analysis",
        label="Analysis",
        role="fast",
        skills=("workspace", "analyze", "science", "calculator"),
        blurb=(
            "Data, maths, plots, and named catalogs over files that already exist. "
            "Charts use plot (Allow) and land in the project's plots folder."
        ),
    ),
    "writing": RoomKind(
        id="writing",
        label="Writing",
        role="research",
        skills=("workspace", "document"),
        blurb="Drafting and revising documents in the project's documents folder.",
    ),
}

DEFAULT_KIND = "general"


def slugify(name: str) -> str:
    """Room id from a spoken name: 'Physics Lab' -> 'physics-lab'.

    Ids are typed into commands, so they stay ASCII, lowercase and hyphenated.
    Accents are folded rather than dropped — 'Café' is 'cafe', not 'caf'.

    A name with no ASCII letters at all slugs to nothing, and the caller rejects
    it. That is a real limit for a room named only in a non-Latin script, and
    the alternative is worse: a generated id like `room-2` is one nobody can say
    out loud, which is the whole way into a room.
    """
    folded = unicodedata.normalize("NFKD", (name or "").strip().lower())
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    purpose: str = ""
    root: str = ""
    kind: str = DEFAULT_KIND
    result: str = ""
    test: str = ""
    setup: str = ""
    tools: tuple[str, ...] = ()
    created_at: str = ""

    @property
    def spec(self) -> RoomKind:
        return KINDS.get(self.kind, KINDS[DEFAULT_KIND])

    @property
    def role(self) -> str | None:
        return self.spec.role

    def prompt_block(self) -> str:
        """What she is told, every turn, while this room is open.

        Deliberately short. It sits alongside the project line, the profile and
        the world state in an already long system prompt, and a room that
        lectures for a paragraph buys its context out of the conversation.
        """
        lines = [f"### Room — {self.name}"]
        if self.purpose:
            lines.append(self.purpose.strip())
        if self.result:
            lines.append(f"A finished result looks like: {self.result.strip()}")
        if self.test:
            lines.append(f"A run counts when: {self.test.strip()}")
        if self.root:
            lines.append(f"Work happens in the `{self.root}` project unless told otherwise.")
            if self.kind == "writing":
                lines.append(
                    "Drafts belong in this project's documents folder. "
                    "A write-up with no format is markdown; PDF, Word, and "
                    "Excel are exports you ask for."
                )
            else:
                lines.append(
                    "Files she creates land in this project's documents folder."
                )
        lines.append(
            "This is a continuing thread about this work. Earlier turns in this "
            "room are yours to build on."
        )
        return "\n".join(lines)

    def to_yaml(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name}
        if self.purpose:
            out["purpose"] = self.purpose
        if self.root:
            out["root"] = self.root
        if self.kind and self.kind != DEFAULT_KIND:
            out["kind"] = self.kind
        if self.result:
            out["result"] = self.result
        if self.test:
            out["test"] = self.test
        if self.setup:
            out["setup"] = self.setup
        if self.tools:
            out["tools"] = list(self.tools)
        if self.created_at:
            out["created_at"] = self.created_at
        return out


def _perma_physics() -> Room:
    return Room(
        id=PHYSICS_ROOM_ID,
        name=PHYSICS_DISPLAY_NAME,
        purpose=PHYSICS_PURPOSE,
        kind="analysis",
    )


# Code-owned. A YAML flag can be deleted; these cannot.
PERMA_ROOMS: dict[str, Room] = {PHYSICS_ROOM_ID: _perma_physics()}


def is_perma(room_id: str) -> bool:
    return slugify(room_id) in PERMA_ROOMS


class RoomStore:
    """Room definitions on disk, plus which one is open right now.

    Being *in* a room is in-process. last_active is the disk hint for the next
    launch: only a room that was entered, still exists, and was not left.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else ROOMS_PATH
        self._rooms: dict[str, Room] = {}
        self._active: str = ""
        self._resume_id: str = ""
        self.reload()

    # -- disk ------------------------------------------------------------

    def reload(self) -> None:
        raw = self._read()
        rooms: dict[str, Room] = {}
        for room_id, body in (raw.get("rooms") or {}).items():
            room = self._room_from_yaml(str(room_id), body)
            if room is not None:
                rooms[room.id] = room
        self._rooms = rooms
        saved = slugify(str(raw.get("last_active") or ""))
        # Set before seed-write so a missing perma room does not drop last_active.
        self._resume_id = saved
        self._ensure_perma()
        if self._resume_id not in self._rooms:
            self._resume_id = ""
        if self._active not in self._rooms:
            self._active = ""

    def _read(self) -> dict[str, Any]:
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, yaml.YAMLError) as exc:
            log.warning("Could not read %s: %s", self.path, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _room_from_yaml(self, room_id: str, body: Any) -> Room | None:
        """One bad room must not cost the operator the other nine.

        A hand-edited file is the point of storing rooms as YAML, and hand
        editing means typos. Anything unreadable is logged and skipped.
        """
        slug = slugify(room_id)
        if not slug:
            log.warning("Skipping room with unusable id %r in %s", room_id, self.path)
            return None
        if isinstance(body, str):
            body = {"name": body}
        if not isinstance(body, dict):
            log.warning("Skipping room `%s`: expected a mapping", slug)
            return None
        kind = _clean(body.get("kind")).lower() or DEFAULT_KIND
        if kind not in KINDS:
            log.warning(
                "Room `%s` has unknown kind `%s`; using `%s`", slug, kind, DEFAULT_KIND
            )
            kind = DEFAULT_KIND
        tools = body.get("tools") or ()
        if isinstance(tools, str):
            tools = [tools]
        setup = _clean(body.get("setup")).lower()
        if setup not in {"", "done", "skipped"}:
            setup = ""
        return Room(
            id=slug,
            name=_clean(body.get("name")) or slug,
            purpose=str(body.get("purpose") or "").strip(),
            root=_clean(body.get("root")),
            kind=kind,
            result=str(body.get("result") or "").strip(),
            test=str(body.get("test") or "").strip(),
            setup=setup,
            tools=tuple(sorted({_clean(t) for t in tools if _clean(t)})),
            created_at=_clean(body.get("created_at")),
        )

    def _ensure_perma(self) -> None:
        """Put permanent rooms back if the file never had them, or forgot them.

        The physics id is permanent. The display name migrated from Physics
        to Reality; a still-default Physics name is rewritten. A custom
        name is left alone. Spoken Reality still resolves via aliases.
        """
        dirty = False
        for room_id, spec in PERMA_ROOMS.items():
            if room_id not in self._rooms:
                self._rooms[room_id] = replace(
                    spec,
                    created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                )
                dirty = True
                continue
            existing = self._rooms[room_id]
            if room_id == PHYSICS_ROOM_ID and existing.name == "Physics":
                self._rooms[room_id] = replace(existing, name=spec.name)
                dirty = True
        if dirty:
            self.save()

    def save(self) -> None:
        body = {
            room_id: self._rooms[room_id].to_yaml() for room_id in sorted(self._rooms)
        }
        header = (
            "# Arelis rooms — a named place to work on one thing.\n"
            "#\n"
            "# Each room keeps its own conversation thread, points at one\n"
            "# workspace project, and hands Arelis its purpose every turn.\n"
            "# Enter one with `/room <name>` or by saying \"let's work on <name>\".\n"
            "#\n"
            "# kind: " + " | ".join(sorted(KINDS)) + "\n"
            "# tools: optional. Leave it out and the room leans without\n"
            "#        restricting; list tool names to lock the room to them.\n"
            "# last_active: written on enter/leave. Launch resumes that room.\n"
            "# physics is permanent (display name Reality). Always present,\n"
            "# cannot be forgotten. Do not add a second room called Reality.\n\n"
        )
        payload: dict[str, Any] = {"rooms": body}
        if self._resume_id and self._resume_id in self._rooms:
            payload["last_active"] = self._resume_id
        text = header + yaml.safe_dump(
            payload,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")

    # -- reading ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self._rooms)

    def all(self) -> list[Room]:
        return [self._rooms[room_id] for room_id in sorted(self._rooms)]

    def get(self, room_id: str) -> Room | None:
        return self._rooms.get(slugify(room_id))

    def find(self, text: str) -> Room | None:
        """Resolve what someone said to a room: id, name, or unique prefix.

        Spoken input arrives without punctuation and often without the exact
        name — "physics" or "Reality" for the permanent room, "some physics"
        for the same place. An ambiguous prefix returns None rather than a
        guess, because entering the wrong room silently swaps both the
        thread and the folder.
        """
        wanted = _clean(text).lower()
        if not wanted:
            return None
        for candidate in (wanted, normalize_room_name(wanted)):
            hit = self._lookup(candidate)
            if hit is not None:
                return hit
        parts = normalize_room_name(wanted).split()
        for n in range(min(3, len(parts) - 1), 0, -1):
            hit = self._lookup(" ".join(parts[:n]))
            if hit is not None:
                return hit
        return None

    def _lookup(self, wanted: str) -> Room | None:
        wanted = _clean(wanted).lower()
        if not wanted:
            return None
        if wanted in PHYSICS_ALIASES or slugify(wanted) in PHYSICS_ALIASES:
            return self._rooms.get(PHYSICS_ROOM_ID)
        direct = self._rooms.get(slugify(wanted))
        if direct is not None:
            return direct
        by_name = [r for r in self._rooms.values() if r.name.lower() == wanted]
        if len(by_name) == 1:
            return by_name[0]
        slug = slugify(wanted)
        prefix = [
            r
            for r in self._rooms.values()
            if r.id.startswith(slug) or r.name.lower().startswith(wanted)
        ]
        return prefix[0] if len(prefix) == 1 else None

    # -- the open room ---------------------------------------------------

    @property
    def active(self) -> Room | None:
        return self._rooms.get(self._active)

    @property
    def active_id(self) -> str:
        return self._active if self._active in self._rooms else ""

    @property
    def last_active_id(self) -> str:
        """Room to resume on launch, if it still exists. Not entered yet."""
        return self._resume_id if self._resume_id in self._rooms else ""

    def set_active(self, room_id: str) -> Room | None:
        room = self.get(room_id) if room_id else None
        self._active = room.id if room is not None else ""
        self._resume_id = self._active
        self.save()
        return room

    def leave(self) -> None:
        self._active = ""
        self._resume_id = ""
        self.save()

    # -- writing ---------------------------------------------------------

    def create(
        self,
        name: str,
        *,
        purpose: str = "",
        root: str = "",
        kind: str = DEFAULT_KIND,
        tools: tuple[str, ...] = (),
    ) -> Room:
        slug = slugify(name)
        if not slug:
            raise ValueError("A room needs a name with letters or numbers in it.")
        if slug in _RESERVED_IDS:
            raise ValueError(
                f"`{slug}` is reserved — it means 'no room' in commands. Pick another name."
            )
        if slug in PHYSICS_ALIASES or slugify(name) in PHYSICS_ALIASES:
            raise ValueError(
                "Reality already exists — it is the permanent room "
                f"(`/room {PHYSICS_ROOM_ID}`). Say \"let's work on Reality\"."
            )
        if slug in self._rooms:
            raise ValueError(f"A room called `{slug}` already exists.")
        if kind not in KINDS:
            raise ValueError(
                f"Unknown room kind `{kind}`. Choose one of: {', '.join(sorted(KINDS))}."
            )
        room = Room(
            id=slug,
            name=_clean(name),
            purpose=purpose.strip(),
            root=_clean(root),
            kind=kind,
            tools=tuple(sorted(set(tools))),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self._rooms[slug] = room
        self.save()
        return room

    def update(self, room_id: str, **fields: Any) -> Room:
        room = self.get(room_id)
        if room is None:
            raise ValueError(f"No room called `{room_id}`.")
        allowed = {"name", "purpose", "root", "kind", "result", "test", "setup", "tools"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Cannot set {', '.join(sorted(unknown))} on a room.")
        if "kind" in fields and fields["kind"] not in KINDS:
            raise ValueError(
                f"Unknown room kind `{fields['kind']}`. "
                f"Choose one of: {', '.join(sorted(KINDS))}."
            )
        if "tools" in fields:
            fields["tools"] = tuple(sorted(set(fields["tools"] or ())))
        if "name" in fields:
            fields["name"] = _clean(fields["name"])
            if not fields["name"]:
                raise ValueError("A room needs a name.")
        updated = replace(room, **fields)
        self._rooms[room.id] = updated
        self.save()
        return updated

    def remove(self, room_id: str) -> bool:
        """Forget the definition. The room's conversations stay in History.

        Deleting the threads too would make a mistyped `/room forget` cost work
        that has nowhere else to live.
        """
        room = self.get(room_id)
        if room is None:
            return False
        if is_perma(room.id):
            raise ValueError(
                f"`{room.id}` is a permanent room — it comes back on launch. "
                "You can leave it, but you cannot forget it."
            )
        del self._rooms[room.id]
        if self._active == room.id:
            self._active = ""
        if self._resume_id == room.id:
            self._resume_id = ""
        self.save()
        return True
