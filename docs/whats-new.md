# What's new (this checkout)

**A person has not walked this checkout.** Nobody sat down, opened **Arelis
(dev)**, and tried the cards, search, texts, weather, or voice the way you
would. What we have is the automated pytest suite from the sitting. That is
not the same thing. Treat it as unreleased source until someone does that
walk.

The installer on GitHub is still **0.2.2**. This file is the living notes for
what the source sitting added on top — so you (or a stranger who clones the
repo) can see what changed without spelunking a chat log.

Nothing here is a version bump. No installer. No GitHub release. Restart
**Arelis (dev)** to feel it. The published 0.2.1 / 0.2.2 notes stay as history.

---

## She asks like a person

Risky things still pause. The card just stopped talking like a debugger.

- The headline is what she wants: **text wife**, **write note.txt**, **open
  youtube**. Not a tool name in backticks.
- Two lowercase buttons: **allow** and **deny**. Deny is this step only — the
  turn keeps going. Esc is deny. Enter is allow.
- Typed **no** / **deny** / **don't** denies. Typed **yes** / **go ahead**
  allows. An empty Enter still allows.
- **Conversation mode** keeps the mic on while the card is up. She explains.
  You say allow or deny. Anything else is ignored — it is not a new question.
- A drive you already typed or said (**open youtube**, **click sign in**) is
  the grant. Her window just moves. If *she* offers a window you did not ask
  for, that still pauses.
- Mail and texts still show the exact message. One allow, then it sends.
- **Settings → Allow** is the real list: files and memory, pictures, her
  window when she offers it, seeing images, mail and texts. Two presets:
  *ask me everything*, or *don't ask about files, pictures, or her window*
  (mail and texts still pause). **Systems ▾ → Allow gates** opens that tab.

The little checkbox on file / picture / window cards is **rest of this ask**
— further steps in this reply, not forever. Mail, texts, and calendar never
ride along.

## She looks things up quietly

Search is still one tool, no keys, no Settings picker.

1. DuckDuckGo HTML
2. DuckDuckGo Lite if that comes back empty
3. Wikipedia — skipped when you asked for news from today or this week

If a page is a hollow JavaScript shell, she tries an RSS/Atom twin when the
site linked one, and she will use a real Open Graph teaser instead of
pretending the page is empty. If it is still a shell, she asks once to open
that URL in her window. She does not invent the page. Every site gets that
path. There is no special case for any one app.

## Texts feel like texts

An inbound SMS flashes the Arelis taskbar if you are in another window, and
the phone tile pulses when this process does not own the OS foreground. The
thread ends at the last bubble — no empty stretch under the conversation.

## Weather and the clock

She can do more than one place in a single ask. Timer phrasing is less
fussy. Listing scheduled jobs does not raise a card; creating or deleting
one still does. “In my inbox” is mail, not a city.

## One model, two moods

This checkout overlays both composer chips onto `qwen3.5:9b`
(`data/config.local.yaml` — not a version bump). **fast** and **research**
are the same weights; research just thinks longer and reaches farther.
File and git work stays on fast. Live 0.2.2 still uses Qwen2.5 7B / 14B.
Details: [models.md](models.md).

## What we threw out

Old sitting plans, canvases, and scratch markdown that already shipped into
the code. This file is the living one for the checkout.

---

Pytest from the sitting was green. That is not a person sitting down with
the window. Your records stay on your disk. She still will not send mail
or a text while you are away from the keyboard.
