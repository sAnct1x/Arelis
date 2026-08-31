# Rooms

A room is a named place to work on one thing. It has its own thread,
its own folder, and a purpose that she reads back to herself at the
start of every turn.

The general conversation is meant to be forgettable — last night's
rambling chat sits quietly in History and that's fine. But work you
actually come back to belongs in a room, and that room comes back
with you.

On a cold launch: if you were inside a room when you left, you're
back in it. If you'd left with `/leave`, you land back in the general
conversation (orbit).

## What a room actually carries

| | |
|---|---|
| **purpose** | Plain language, written once. She reads it at the start of every turn in the room. |
| **root** | The workspace folder the work lives in. Entering the room makes it active. |
| **kind** | The lean — which model she reaches for first, which skills she leans on. |
| **thread** | Its own conversation, picked back up when you walk in, never mixed with the general one. |

The thread is really the part that matters. Everything else is just
convenience around it.

## Getting in and out

```
/rooms                     what exists
/room physics              go in (slash id)
/leave                     come back out
```

Or just say it — "let's work on Reality," "open Reality," "enter
Reality," "leave the room" all work, and `/room physics` gets you to
the same place. Older phrasing like "open world" or "open the solar
lab" still gets you into Reality, but those names themselves are gone
now. Spoken navigation only fires on a room name that already exists
— if you say "let's work on the budget" and there's no budget room,
that's just treated as an ordinary sentence.

The room id `physics` is permanent. Humans read **Reality**. That room
is always there — `/room forget physics` gets refused, and if you
delete the entry from `rooms.yaml` by hand, the next launch just puts
it back. Don't create a second room also called Reality. Earth is a
zone inside Reality, not its own room.

Installed copies still get Reality as a room — chat, CAS, Horizons,
all of it works. But the 3D solar system, the C920 hand tracking, and
the Earth view only run from a source checkout with `.[astro]` /
`.[spatial]` installed — none of that ships in the installer. Say
"open Reality," or use View → Reality (Ctrl+8). Saying "travel to
Earth", "enter Earth", or "take me to Tokyo" opens the Earth view
on the globe — see
[earth.md](earth.md). Pose and spoken Reality commands act directly
on the scene without needing a chat turn. Just note: the phone isn't
a sensor here, and this room isn't meant to become a spreadsheet
workspace — make a separate room for that kind of work.

## Making one

Just ask her, in plain language:

> make me a survey room for analysing the field data, working in my
> Lab Notes folder

She'll fill in the purpose and the folder from what you said, then
show you an allow / deny card before anything actually gets written.

Or say **"let's work on survey"** (or `/room new survey`). The first
time you walk into an empty room she asks in the chat — what it is
for, which folder, what a finished result looks like, how you will
know a run happened. Typed or spoken is the same path. Your answers
write the room. Say **skip** for one question, **later** to stop, or
**set up this room** to start again. You can also say the fields
anytime: "this room is for analysing the field data", "work in Lab
Notes", "make it an analysis room".

Slash still works if you want it:

```
/room new survey
/room set purpose analysing the field data
/room set root Lab Notes
/room set kind analysis
```

`/room new` also puts you inside the room right away. Adding an entry
to `rooms.yaml` by hand, without actually going in, doesn't count as
entering it. Reality already has a contract — she does not interview
you there.

`/room forget survey` removes the definition, but its past
conversations stay put in History — only the room itself disappears.
A forgotten room won't come back on the next launch, with one
exception: Reality, which can never be forgotten.

## Kinds

| kind | model | for |
|---|---|---|
| `general` | whatever you were using | no particular lean |
| `code` | fast | reading and writing files, running tests |
| `analysis` | fast | data, math, plots, named catalogs |
| `research` | research | reading widely, keeping notes, citing sources |
| `writing` | research | drafting and revising documents in the project's `documents` folder |

A kind is a starting bias, not a lock — `/role` still overrides it,
and every tool still works in every room regardless of kind. The kind
just shifts which skills she reaches for first; it's not a smaller
toolset (the full schema array actually gets sent every turn, on
purpose, so the prefix cache holds). Think of it as a menu bias
rather than a fixed plan — `kind: analysis` doesn't mean every
sentence you type gets treated as a spreadsheet. Ask what a toroid is
in an analysis room and you'll just get an answer; the analyze tool
only kicks in when you actually name a table.

## Rooms lean, they don't cage

If you ask the time while in Reality and a caged assistant has to
refuse, that just teaches you to stop asking questions there. So by
default, entering a room changes what she reaches for first — and
nothing else.

If you genuinely want a locked-down room, you can name the exact
tools it's allowed to use in `data/rooms.yaml`:

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

Once you do that, the room offers only those tools and nothing else.
If a `tools:` list ends up matching no real tool (say, a typo), it's
simply ignored — otherwise a small mistake there would leave her with
nothing to work with at all.

## Where things actually live

- **`data/rooms.yaml`** — the room definitions themselves.
  Hand-editable; see `data/rooms.example.yaml` for the format. Lives
  under your records folder: `%LOCALAPPDATA%\Arelis\data` if
  installed, or `data\` in the repo if you're running from source.
- **`data/memory.db`** — the actual threads. Every conversation row
  is tagged with the room it belongs to, so History can show them
  properly and the cold-launch cleanup can't touch them.
- **Generated files** (PDF, Word, spreadsheet, markdown) land in
  `<project>/documents/` while you're working inside a room with a
  folder attached. Charts land in `<project>/plots/`. One-off files
  made outside a room still go to `outputs/documents/` and
  `outputs/plots/`.

## Launch behavior

Whichever room you were actually *in* when you last used her comes
back automatically on the next launch. If you'd rather start in the
general conversation, leave the room before you close her. Just
creating a room doesn't count as entering it. And scheduled jobs
never resume a room on their own.

This isn't a second window, either — just a strip above the
transcript naming the room, its purpose, its folder, and a way back
out. The conversation itself stays on the same surface it's always
been. In Reality specifically, the 3D view is its own floating
window, not a second chat.
