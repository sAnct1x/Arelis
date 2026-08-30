# Rooms

A room is a named place to work on one thing: its own thread, a folder,
and a purpose she reads at the start of every turn.

The general conversation is meant to be forgettable. Last night in
orbit sits in History. Work you come back to belongs in a room, and
that room comes back with you.

Cold launch: if you left inside a room, you are in it again. If you
left with `/leave`, you are in orbit.

## What a room carries

| | |
|---|---|
| **purpose** | Plain language, written once. She reads it at the start of every turn in the room. |
| **root** | The workspace folder the work lives in. Entering the room makes it active. |
| **kind** | The lean: which model she reaches for first, which skills she leans on. |
| **thread** | Its own conversation, resumed when you walk in, never mixed with general. |

The thread is the part that matters. Everything else is convenience.

## Getting in and out

```
/rooms                     what exists
/room physics              go in (slash id)
/leave                     come back out
```

Or say it: "let's work on Reality", "open Reality", "enter Reality",
"leave the room". `/room physics` is the same place. Older words
("open world", "open the solar lab") still enter Reality — those
names are gone. Spoken navigation only fires on a name that already
exists. "Let's work on the budget" in a house with no budget room is
an ordinary sentence.

The room id `physics` is permanent. Humans read **Reality**. It is
always there, and `/room forget physics` is refused. Delete the key from
`rooms.yaml` and the next launch puts it back. Do not add a second room
called Reality. Earth is a zone inside Reality, not a room.
Contacts there use one drawn mark language ([earth.md](earth.md)).

Installed copies still get Reality (chat, CAS, Horizons). The plate,
REBOUND solar system, C920 hands, and Earth zone run only on a **source
checkout** with `.[astro]` / `.[spatial]`. Not in the installer. Say
"open Reality" or View → Reality / Ctrl+8. Travel to Earth (or say
**enter Earth**) opens the Earth zone on that globe.
[earth.md](earth.md). Pose and spoken Reality verbs hit the scene without
a chat turn. The phone is not a sensor. Do not turn this room into a
spreadsheet workspace; make a different room for that.

## Making one

Ask:

> make me a survey room for analysing the field data, working in my Lab Notes
> folder

She fills in the purpose and the folder from what you said, then shows an
allow / deny card before anything is written. Or do it by hand:

```
/room new survey
/room set purpose analysing the field data
/room set root Lab Notes
/room set kind analysis
```

`/room new` also enters the room. Creating one in `rooms.yaml` by hand,
without going in, does not.

`/room forget survey` removes the definition. Its conversations stay in
History. Only the room is gone. A forgotten room is not recreated on
launch, except Reality: that one cannot be forgotten.

## Kinds

| kind | model | for |
|---|---|---|
| `general` | whatever you were using | no lean |
| `code` | fast | reading and writing files, running tests |
| `analysis` | fast | data, maths, plots, named catalogs |
| `research` | research | reading widely, keeping notes, citing sources |
| `writing` | research | drafting and revising documents in the project's `documents` folder |

A kind is a starting chip, not a lock. `/role` still overrides it. Every
tool still works in every room. The kind's skills are a lean (which
cards she reaches for first), not a smaller tool list — shipped config
sends the full schema array every turn so the prefix cache holds. It is
a menu bias, not a plan: `kind: analysis` does not mean every sentence
is a spreadsheet. Asking what a toroid is still gets an answer;
`analyze` runs when the ask actually names a table.

## Rooms lean, they do not cage

Ask the time in Reality and a caged assistant has to refuse, which
teaches you to stop asking. So by default a room changes what she
reaches for first and nothing else.

If you genuinely want a locked room, name the tools in `data/rooms.yaml`:

```yaml
rooms:
  survey:
    name: Survey
    purpose: Analysing the field data.
    root: Lab Notes
    kind: analysis
    tools:
      - workspace
      - calculator
      - analyze
```

Then that room offers those and nothing else. A `tools:` list that
matches no real tool is ignored, because a typo there would otherwise
leave her with nothing.

## Where things live

- `data/rooms.yaml`: the definitions. Hand-editable. See
  `data/rooms.example.yaml`. Under your records folder:
  `%LOCALAPPDATA%\Arelis\data` installed, or `data\` in the repository
  from source.
- `data/memory.db`: the threads. Each conversation row carries the room
  it belongs to, so History shows them and the cold-launch prune cannot
  touch them.
- Files she creates (PDF, Word, spreadsheet, markdown) land in
  `<project>/documents/` while you are in a room with a folder. Charts
  land in `<project>/plots/`. Orbit one-offs still go to
  `outputs/documents/` and `outputs/plots/`.

## Launch

The last room you actually entered comes back on the next start. Leave
first if you want orbit. A room you only created is not entered. Jobs
never resume a room.

This is not a second window. A strip above the transcript names the
room, its purpose, and its folder, and a way out. The conversation
itself is the same surface it always was. In Reality, the plate is a
separate floating window, not a second chat.
