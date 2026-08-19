# What's new (this checkout)

The installer on GitHub is still **0.2.2**. This file is the living notes
for the source sitting on top of that. No version bump. No installer.
No GitHub release. Restart **Arelis (dev)** to feel it.

Phone pairing on this checkout was walked: scan the QR, send, receive.
The rest of the window (cards, search, weather, voice, science) has
pytest from the sittings, not a full person sitting down with the glass.
Treat the checkout as unreleased until someone does that walk.

The published 0.2.1 / 0.2.2 notes stay as history.

## She asks like a person

Risky things still pause. The card just stopped talking like a debugger.

- The headline is what she wants: **text wife**, **write note.txt**,
  **open youtube**.
- Two lowercase buttons: **allow** and **deny**. Deny is this step only.
  The turn keeps going. Esc is deny. Enter is allow.
- Typed **no** / **deny** / **don't** denies. Typed **yes** / **go ahead**
  allows. An empty Enter still allows.
- Conversation mode keeps the mic on while the card is up. Say allow or
  deny. Anything else is ignored.
- A drive you already typed or said is the grant. Her window just moves.
  If she offers a window you did not ask for, that still pauses.
- Mail and texts still show the exact message. One allow, then it sends.
- **Settings → Allow** is the list. Two presets: ask me everything, or
  skip files, pictures, and her window (mail and texts still pause).
  **Systems ▾ → Allow gates** opens that tab.

The little checkbox on file / picture / window cards is **rest of this
ask**: further steps in this reply, not forever. Mail, texts, and
calendar never ride along.

## She looks things up quietly

Search is still one tool. No keys. No Settings picker.

1. DuckDuckGo HTML
2. DuckDuckGo Lite if that comes back empty
3. Wikipedia, skipped when you asked for news from today or this week

If a page is a hollow JavaScript shell, she tries an RSS or Atom twin
when the site linked one, and she will use a real Open Graph teaser
instead of pretending the page is empty. If it is still a shell, she
asks once to open that URL in her window. She does not invent the page.

## Texts feel like texts

An inbound SMS flashes the Arelis taskbar if you are in another window,
and the phone tile pulses when this process does not own the OS
foreground. The thread ends at the last bubble.

## One phone app

One sideloaded **Arelis** app (`applicationId` `app.arelis`). Campfire
UI. Google Messages inbound, including RCS. A LAN radio so she can send
SMS from this SIM after you allow the card. Pair from Settings → Notify.
Google Messages stays your messenger. Uninstall the old Notify APK
first. If she had no SMS radio before this pair, restart **Arelis (dev)**
once so `send_sms` appears. Details:
[notify-inbound.md](notify-inbound.md).

## Weather and the clock

She can do more than one place in a single ask. Timer phrasing is less
fussy. Listing scheduled jobs does not raise a card. Creating or deleting
one still does. "In my inbox" is mail, not a city.

## One model, two moods

This checkout overlays both composer chips onto `qwen3.5:9b` in
`data/config.local.yaml`. **fast** and **research** are the same weights.
Research thinks longer and reaches farther. File and git work stays on
fast. Live 0.2.2 still uses Qwen2.5 7B / 14B. Details:
[models.md](models.md).

## Closed forms are a tool

The pocket calculator still does arithmetic. This checkout adds a CAS
(SymPy) and units plus published constants (Pint). Ask for the integral
of x² sin x, or convert 5 ft 8 in to meters, and she has to call a tool
this turn. Hubble comes back as both published figures plus the tension.
No closed form means she says so. Arithmetic stays on the calculator.

## Charts are a file

Ask her to plot a CSV, or to fit a line and plot residuals. She has to
call **plot** this turn. You see an Allow card, then a PNG under
`outputs/plots/`. She does not sketch ASCII. She does not run your
Python. Residuals quote the slope, intercept, and R², plus a sidecar
CSV. Overnight jobs do not plot while you are away. Matplotlib is in
the default `pip install -e .`.

## Catalogs

Ask her to search arXiv, or where Mars is tonight, and she has to call
**catalog**. arXiv and JPL Horizons need no key. NASA's picture of the
day and NASA ADS need a free key in `data/secrets.yaml`
(`nasa.api_key`, `ads.token`). She will not use DEMO_KEY. She will not
invent a bibcode. Abstracts are treated as untrusted text. NASA and ADS
keys can wait.

Your records stay on your disk. She still will not send mail or a text
while you are away from the keyboard.
