# Rooms

A room is a named place to work on one thing — like walking into a studio
with the lights already on.

The general conversation is meant to be forgettable. Cold launch gives you an
empty orbit, last night sits in History, and that is right for "what's the
weather" or "text him I'm running late". It is wrong for work you come back to:
a three-week analysis, a paper, a codebase. That work needs somewhere that
remembers where it got to, already knows which folder it lives in, and does not
have to be re-explained every launch.

## What a room carries

| | |
|---|---|
| **purpose** | Plain language, written once. She reads it at the start of every turn in the room. |
| **root** | The workspace project the work lives in. Entering the room makes it active. |
| **kind** | The lean — which model she reaches for first, which skills she leans on. |
| **thread** | Its own conversation, resumed when you walk in, never mixed with general. |

The thread is the part that matters. Everything else is convenience; a room
without its own conversation is a system prompt with extra steps.

## Getting in and out

```
/rooms                     what exists
/room physics              go in
/leave                     come back out
```

Or say it: **"let's work on physics"**, **"open the physics room"**,
**"leave the room"**. Speaking works because it goes through the same command
path a typed line does.

Spoken navigation only fires on a name that already resolves to a room. "Let's
work on the budget" in a house with no budget room is an ordinary sentence and
stays one — nothing moves.

## Making one

Ask:

> make me a physics room for analysing the survey data, working in my Lab Notes
> folder

She fills in the purpose and the folder from what you said and shows an
allow / deny card before anything is written. Or do it by hand:

```
/room new physics
/room set purpose analysing the survey data
/room set root Lab Notes
/room set kind analysis
```

`/room forget physics` removes the definition. **Its conversations stay in
History** — only the room is gone.

## Kinds

| kind | model | for |
|---|---|---|
| `general` | whatever you were using | no lean |
| `code` | fast | reading and writing files, running tests |
| `analysis` | fast | data, maths and plots over files that exist |
| `research` | research | reading widely, keeping notes, citing sources |
| `writing` | research | drafting and revising documents |

A kind is a starting chip, not a lock. `/role` still overrides it, and every
tool still works in every room.

## Rooms lean, they do not cage

The obvious design is a tool allowlist per room, and it is the wrong default.
Ask the time in the physics room and a caged assistant has to refuse, which
teaches you to stop asking. So by default a room changes what she reaches for
first and nothing else.

If you genuinely want a locked room, name the tools in `data/rooms.yaml`:

```yaml
rooms:
  physics:
    name: Physics
    purpose: Analysing the survey data.
    root: Lab Notes
    kind: analysis
    tools:
      - workspace
      - calculator
      - analyze
```

Then that room offers those and nothing else. A `tools:` list that matches no
real tool is ignored rather than obeyed, because a typo there would otherwise
leave her with nothing.

## Where things live

- `data/rooms.yaml` — the definitions. Hand-editable; see
  `data/rooms.example.yaml`. Under your records folder:
  `%LOCALAPPDATA%\Arelis\data` installed, or `data\` in the repository from
  source.
- `data/memory.db` — the threads. Each conversation row carries the room it
  belongs to, so History shows them and the cold-launch prune cannot touch them.

## What rooms deliberately do not do

**They do not survive a launch.** You always start in the general orbit and step
into a room on purpose. A launch that silently resumed three-week-old context,
with a different model and a different folder already active, would be a mode
you did not choose and could not see.

**They are not a second window.** The room paints a strip above the transcript
with its name, purpose and folder, and a way out. The conversation itself is the
same conversation surface it always was.
