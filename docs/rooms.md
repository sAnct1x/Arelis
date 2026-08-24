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
/room physics              go in
/leave                     come back out
```

Or say it: "let's work on physics", "open the physics room", "leave the
room". Spoken navigation only fires on a name that already exists.
"Let's work on the budget" in a house with no budget room is an ordinary
sentence.

The room id `physics` is reserved. It is the spatial stage: World plate
and C920 tracking run only there. Pose updates the scene without a chat
turn. Spoken world verbs are parked. The phone is not a sensor. Do not
turn this room into a spreadsheet workspace; make a different room for
that.

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
launch. Do not forget `physics` unless you mean to drop the spatial
stage.

## Kinds

| kind | model | for |
|---|---|---|
| `general` | whatever you were using | no lean |
| `code` | fast | reading and writing files, running tests |
| `analysis` | fast | data, maths, plots, named catalogs |
| `research` | research | reading widely, keeping notes, citing sources |
| `writing` | research | drafting and revising documents in the project's `documents` folder |

A kind is a starting chip, not a lock. `/role` still overrides it. Every
tool still works in every room. The kind's skills are offered first on
every turn in that room — that is the lean. It is a menu bias, not a
plan: `kind: analysis` does not mean every sentence is a spreadsheet.
Asking what a toroid is still gets an answer; `analyze` runs when the
ask actually names a table.

## Rooms lean, they do not cage

Ask the time in the physics room and a caged assistant has to refuse,
which teaches you to stop asking. So by default a room changes what she
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
itself is the same surface it always was. In `physics`, the World plate
is a separate floating window, not a second chat.
