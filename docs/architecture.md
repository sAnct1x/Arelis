# How the code is put together

This is a map of the tree as it exists right now. Install steps and
day-to-day use live in the [README](../README.md) — this doc is just
the "how it actually works underneath" version. Living notes for
whatever you've checked out are in [whats-new.md](whats-new.md).

Arelis is a local tool-calling agent running on this PC. The model
itself never leaves this machine. Everything outside it — the web,
your files, mail, whatever — only happens because a tool call you
started reached out, or because you approved a card asking for
permission.

## Ways in

| How | When |
|---|---|
| Window (`.\scripts\run_ui.ps1`) | Normal day-to-day use: chat, docks, Settings |
| CLI (`arelis --cli`) | Same brain, just in a terminal |
| Core (`.\scripts\run_core.ps1`) | Background only: phone messages, jobs, no window at all |
| Tray | Window's hidden but she's still running. The taskbar X and the title bar's close button just hide her — **Quit Arelis** in the tray is the actual exit |
| Job (`arelis --run-job <id>`) | One unattended turn, then an email with the result. See [jobs.md](jobs.md) |

Core and the UI talk to each other over a small loopback bridge, which
is why inbound texts and "open the window" still work even when the
window itself is closed. `--core` never runs the first-open setup
wizards — it just uses whatever defaults exist until the window is
actually opened.

The phone app is a LAN companion, not a second copy of Arelis. When
your PC is reachable, chat on the phone is literally the same live
session. When it isn't, the phone keeps its own seat and just picks
up the conversation — any Gemma-generated words from that time sync
back once the PC is up again. See
[notify-inbound.md](notify-inbound.md).

## First open

It's not really a tour — just two questions, and only in the window:

1. Which folder is she allowed to read, create, change, and delete
   in?
2. She looks at your graphics memory, RAM, and disk, and recommends
   one Qwen 3.5 tag. You can confirm it, or pick Gemma / DeepSeek
   instead.

If Ollama isn't already installed, she downloads the official Windows
engine into `%LOCALAPPDATA%\Arelis-runtime`, then pulls whichever tag
you chose plus `nomic-embed-text`. That pins both Fast and Research
to the same tag in `config.local.yaml`. If a copy has already pinned
`models.fast`, you won't be asked again. Vision support waits until
the first time you actually send a picture. More on all this in
[models.md](models.md).

## What happens in one turn

1. Your text (or a voice transcript) hits the orchestrator
   (`arelis/core/orchestrator.py`). Typed and spoken input share this
   exact same path once the transcript exists — only one turn runs at
   a time.
2. Slash commands (`/role`, `/room`, `/leave`) and spoken room names
   get handled right here. Entering a room, notably, is not itself a
   tool call.
3. The role model actually thinks (`arelis/core/agent_loop.py`). Tool
   schemas are already sitting in the prompt from the launch seed, so
   she may go ahead and call tools.
4. Risky actions pause for your input. A drive you already asked for
   doesn't need to pause again — mail and texts always do, no
   exceptions.
5. Tool results flow back into the turn, and she answers based on
   what she actually got back — not what she expects to get back.

If she's about to state a number she can't actually back up, the
finish gates can step in and have her decline to sound confident
instead.

Native tool calling is the normal path here. The JSON fallback only
kicks in when Ollama rejects the tools array outright, or when the
first round comes back empty with no tool called yet. If a tool
already succeeded earlier in the turn and the next round comes back
with empty chat content, she just answers from that existing result
rather than dropping into JSON mode. Writes and sends still wait for
your approval regardless of which path she took to get there.

The confirmation card itself is written in plain human language —
"text wife," "write note.txt" — nothing cryptic. **Deny** only
blocks that one step. **Stop** ends the whole turn. Conversation
mode (and anything still listening after a wake word) can hear
"allow," "deny," "stop," or a spoken edit to a draft without needing
to start a whole new turn. After a stop, the next thing you say is
just treated as ordinary conversation — she only gets a quiet note
that she was stopped. Idle wake stays deaf on purpose, so background
noise like Discord chatter never accidentally becomes a decision.
**Settings → Allow** is where the full list of what she can do
without asking lives. Mail, texts, and calendar access never
piggyback on approval for something else.

Even a tiny ask — the time, a greeting, a "thanks," "who are you" —
still sends the full tool schema array, so the prefix cache stays
intact. What it skips is the unmatched-web floor, the "call a tool
first" nudge, and holding back the answer until a tool round finishes
— those small turns just stream straight through. "Who is this"
(pointed at a photo, or someone on TV) isn't treated as an identity
question and may still trigger a search. Something like "what time
is it in Tokyo" still needs an actual tool call. Anything that comes
back genuinely unmatched still fails open rather than silently
refusing.

Every launch after the first pins the chat model, then seeds
Ollama's prefix cache (`arelis/llm/startup.py`) with the persona, the
telegraph policy, and the skinny tool schema array — about 5,500
tokens, identical every single turn. On a 12 GB card, that seeding
used to take roughly 40 seconds on the fat prefix; the seed is now
about a third the size. After that, a warm hello takes about
a second. The window shows **loading the model…** while that seed is
running — it won't say **thinking…** until an actual turn has
started.

## Packages

| Piece | Path | Job |
|---|---|---|
| Bus | `arelis/core/bus.py` | Events between the UI and the brain |
| Orchestrator | `arelis/core/orchestrator.py` | Runs one turn at a time; resumes the last room on a new empty chat |
| Agent loop | `arelis/core/agent_loop.py` | Model, tools, confirmations, finish rules |
| Skills | `arelis/core/skills.py` | Which tools she leans toward |
| Router | `arelis/llm/` | Picks the role model, warms it, unloads it |
| Setup | `arelis/setup/` | First-open flow: hardware, model, voice weights, pulling |
| Startup | `arelis/llm/startup.py` | Pins the chat model, seeds the prefix cache |
| Tools | `arelis/tools/` | Everything she can actually call — registry lives in `__init__.py` |
| Jobs | `arelis/jobs/` | The unattended runner plus Task Scheduler integration |
| Browser | `arelis/browser/` | Her own Chrome instance |
| UI | `arelis/ui/` | Window, empty session, docks |
| Presence | `arelis/presence/` | Core process, tray, IPC |
| Voice | `arelis/voice/` | Listening and speaking; `prepare.py` is the first-open fetch — [voice-wake.md](voice-wake.md) |
| Spatial | `arelis/spatial/` | World engine, grants, hand-tracking takes. Pose input is not a chat turn |
| Earth | `arelis/earth/` | Earth view on Reality's globe — 108 shipped / 25 keyed / 3 coming later / 4 left out. Marks come from `arelis/ui/earth_marks.py`. See [earth.md](earth.md) |
| Physics | `arelis/physics/` | Reality's solar system — Horizons initial conditions, REBOUND, IAU attitude |
| Calendar | `arelis/calendar/` | Google / Outlook OAuth — see [calendar-oauth.md](calendar-oauth.md) |
| Memory | `arelis/memory/` | SQLite archive plus recall |
| Config | `arelis/config/default.yaml` | Shipped defaults; overrides live under `data/` |
| Paths | `arelis/paths.py` | Resolves installed vs. checkout roots. Always use this — never hand-write a path for a write |

Only one chat model ever sits in graphics memory at a time. First
open recommends a tag based on your hardware, pins both Fast and
Research to it, and sizes the context window to whatever card it
detected. The shipped last-resort in `default.yaml` is `qwen3.5:9b`
for both Fast and Research — Research mode is just a deeper reasoning
loop on the same weights. File work always stays on Fast. That model
can see images itself, so `models.vision` only exists as a fallback
for a model that can't. Full details in [models.md](models.md).

The persona text and the compact tool-policy block stay byte-identical
across every turn. Shipped config keeps the full skinny tool schema
array (`skill_tool_subset` and `research_tool_subset` are both false).
A per-turn 6-tool subset was actually tried and measured, and it lost:
because the array sits near the front of the prompt, shrinking it
blows out the prefix cache and turns a ~3 second prefill (after the
initial seed) into ~17 seconds, every single turn.
`scripts/measure_tool_surface_prefill.py` has the receipts.
Independent reads within the same round can run concurrently; writes
and anything pause-gated always run one at a time.

Two things are still allowed to change the tools JSON on purpose:
`send_sms` / `send_email` stay hidden unless the current message
actually asked to send something (a safety measure — a plain greeting
used to accidentally replay the last draft), and a room that
explicitly lists `tools:` locks the set down to just those. Leave
that list off unless you genuinely mean to restrict a room. If
`skill_tool_subset` is missing from a partial config, the loop
defaults it to false — don't flip it on just to "go faster."

## The window

An empty session is what we call orbit — a warm void, a ring, and a
text box underneath it. Typing stays there until you actually send
it. Once you do, you land in the full workbench: chat, composer, and
docks.

| Piece | Job |
|---|---|
| Composer | Idle: a centered prompt box. Workbench: a bottom row plus Fast / Research toggle |
| Title strip | Arelis branding, view menu, settings, window buttons |
| Readiness | Ollama status and a house indicator. Mail / SMS / calendar only show up here once connected |
| Chat stage | Empty-session view, the streaming answer, Sources, allow / deny cards. The last finished answer gets a **copy · again** option |
| Drive strip | Stop / Pause / your-turn controls while her browser is actively driving |
| Thinking dock | The actual thinking paragraph. A tool errand shows as one line in that stream. Housekeeping info (model loaded, speech status) sits in a footer, not mixed into the reasoning |
| Workspace dock | The desk: notes you kept and files she wrote, pinned first. Folders is the old tree. Markdown reads as a page. `keep this:` writes a note |
| Camera dock | Webcam still image. View → Camera / Ctrl+5. Inside Reality: Track / Record |
| History dock | Past sessions (shown as **new chat** if untitled), grouped today / yesterday, plus pending facts to approve or reject |
| Notifications | Inbound texts, shown while the UI is open |
| Contacts | People you can text, under View → Contacts / Ctrl+6 |
| Calendar | Local tile, Ctrl+7 — month / week / day / agenda views, plus tasks and jobs. Empty of any Google events until you authorize |
| Settings | Audio / window / allow / notify / roots / memory. Mail and calendar credentials aren't a Settings tab at all — they live in `data/secrets.yaml` and are set up via [calendar-oauth.md](calendar-oauth.md) |
| Themes | View → Themes. **sodium** is the shipped face. **filament (testing)** is a checkout experiment for a row of desks — three monitors is the intended layout; 1 and 2 still work. Saved to `data/config.local.yaml`. Filament is a desk presence: coil at first rest or away-idle, unwrapped once in use. Slim title bar, say “hey arelis”, and 1 / 2 / 3 stay on the primary desk. 1 / 2 / 3 are desk counts, not Windows monitor numbers; default is one primary desk. Text lives on the chat plate. The thinking title breathes while a turn is running. Each title has its own particle on the current (same motion as the word). Click the bead or the word. HWND stays opaque; tiles are floating resizable plates. The field paints a horizontal band and remasks only on span / resize, not every atmosphere tick. Dust stamps live in RAM; camera preview convert is a worker, not the HWND thread |
| Display | Same model as Chrome / VS Code / Office. Qt 6 per-monitor DPI: a 4K panel at 150% is ~2560×1440 logical, not a second 4K mode. First-launch size (1440×900) shrinks to the current work area so 1080p fits; 2K and 4K stay that size until you maximize. Restored geometry that landed on an unplugged monitor moves back. Settings → window → Interface scale is an optional zoom on top of the OS (`ui.scale`, default 1.0, needs a restart). Chat text size is just the transcript (Ctrl+= / − / 0). |
| Reality | A floating 3D window. View → Reality / Ctrl+8. Only appears while the Reality room is active, and only on a source checkout (`world_stage_allowed`). Needs `pip install -e ".[spatial]"` for hand tracking and `.[astro]` for REBOUND — none of it ships in the installer. Default size 1280×800. The solar GPU path is `--solar-gl` / `ARELIS_SOLAR_GL=1` (an offscreen FBO). The Earth view renders the planet through Cesium, with Arelis handling stars and the HUD; contacts there use `earth_marks.py`. It's inspect-only — a WASD fly camera, with H reciting the live key bindings. There's no piloted chase-cam |

Under **Settings → window**, you can have unused panels fold away
after 30, 45, or 60 minutes of no clicking, typing, sending, or wake
word — it's off by default. Any turn, card, latched conversation, or
an active Drive strip resets that timer.

An inbound text flashes the taskbar if you're working in another
window, and the phone tile itself pulses whenever this process
doesn't own OS foreground focus.

The status line about the Phone Notify URL shows up in the thinking
dock's footer, not in chat — putting it directly into chat used to
hide the empty session on a cold launch, so it got moved. The pairing
QR code lives under **Settings → Notify**.

## Tools, briefly

All tools are registered in `arelis/tools/__init__.py`. Scheduled
jobs specifically leave out sending, browser, vision, plotting,
documents, solar, Earth, the archive tools, and anything else that
genuinely needs a person present. `cas`, `units`, `catalog`,
`python`, and `calculator` are all safe to run unattended — see
[jobs.md](jobs.md).

`send_email` / `inbox`, `send_sms` / `inbound_sms`, and `agenda` only
get registered once mail, the phone, or a calendar source is actually
connected. Until then, if you ask, she'll just tell you she can't.

| Tool | Plain English | Pauses? |
|---|---|---|
| `web_search` | Find pages | No |
| `scrape` / `web_fetch` | Read a page for her | No |
| `research_report` | Multi-source write-up, saved under `outputs/research/` | No* |
| `browser` | Drive her Chrome | Only when she offers it — a drive you asked for counts as the grant |
| `workspace` | Files in allowed roots | Writes: yes |
| `analyze` / `doc_extract` / `git_info` | Tables, PDFs, git | No |
| `calculator` | Arithmetic | No |
| `python` | Short numerics cell (math / sympy / numpy). No file or shell access | No |
| `run_script` | A project `.py` under a workspace root. Not a shell. Not her own tests | Yes (card / spoken on filament) |
| `cas` / `units` | Closed forms, conversions, constants | No |
| `diagnostics` | Her own pytest suite. Source checkout with `tests/` needed | No |
| `tile` | Open or close a View-menu panel (thinking, calendar, world, …) | No |
| `plot` | Produces a PNG. Room → `plots/` inside the project; outside a room → `outputs/plots/` | Yes |
| `document` | PDF, Word, Excel, CSV, markdown. Room → `documents/` inside the project; outside a room → `outputs/documents/` | Yes |
| `catalog` | arXiv, Horizons; APOD / ADS once you add a free key | No |
| `solar` | Reality's N-body sim (Horizons VECTORS + REBOUND IAS15). Source checkout only. Approach and orbit views, inspect-only fly camera, IAU spheres. No landing | Yes |
| `earth` | The Earth view inside Reality. Inventory lives in `feeds.py` (108 shipped / 25 keyed / 3 coming later / 4 left out). Source checkout only — see [earth.md](earth.md) | No |
| `clipboard` / `ocr` / `vision` / `camera` | Paste, read screen text, look at an image, use the webcam | Yes (the still capture itself is free; actually looking at it pauses) |
| `memory` / `recall` / `tasks` / `goals` | Remembering things, chores, "what needs my attention" | Mutates: yes |
| `inbox` / `send_email` / `schedule` | Mail and timed jobs | Sending: yes. Creating a job: yes. Listing the inbox is free; trash / archive / move / flag actions: yes |
| `send_sms` / `inbound_sms` | Texting out / listing what's come in | Sending: yes |
| `agenda` | Calendar | Writes: yes |
| `weather` / `user_location` | Forecast / where she thinks you are | No |
| `image` | New picture, via a local ComfyUI instance | Yes |
| `image_edit` | Resize and recolor an existing file | Yes |
| `rooms` | Named project spaces | Creating / changing: yes |
| `contacts` | People available for texting | Mutates: yes |

She can `workspace`-read her package to answer "how do you work"
from the file. Installed copies get a read-only `source` root at
the package.

\* Writes a local file. Outbound mail and texts always need their own
separate allow / deny prompt and are never batched together with
other tools. `research_report` doesn't currently pop up an Allow card
at all.

ComfyUI is a separate app entirely — Arelis never starts it
automatically at launch. `tools.image.auto_start` ships set to false;
if you set it to true and point `launch_cwd` at your ComfyUI install,
the first image request may start it up for you. Until then, asking
for a picture just reports that it's unavailable, rather than trying
to launch something that isn't there.

`scrape` reads a URL for her with no window opening at all.
`browser` moves her own Chrome instance under
`data/browser-profile/` — it's never your everyday Chrome. See
[browser-control.md](browser-control.md).

## Rooms

A room is a named place to work on one thing — its own thread, its
own folder, and a purpose she reads back at the start of every turn.
`/room physics` takes you in, `/leave` takes you out, and launch
resumes whichever room you last entered — on a new empty chat, not
the last filled thread. The room id `physics` is permanent: it's
always present, can't be forgotten, and it's the only place the 3D
view and C920 hand tracking actually run. See [rooms.md](rooms.md).

## Memory and safety

- Chat history is a sliding window (`agent.history_max_messages`,
  shipped at 120 — roughly 60 turns).
- The History dock shows past sessions plus any pending facts
  waiting for approval or rejection.
- Active facts live in `memory.db`, managed under **Settings →
  Memory**. A page you want to reopen is a desk note (`keep this:`),
  not a fact.
- Workspace roots are only the folders you've explicitly configured
  — writes always wait for approval. A path you named in chat can
  get a read-only session grant (Allow). Granting a folder includes
  the files inside it. A deny does not mean she should list
  `Documents` or `C:\Users`.
- Attachments get staged as copies under `data/drops/`.
- Loopback and LAN URLs are blocked for any fetch the model itself
  initiates.
- Scrape results, search results, inbox contents, inbound texts, OCR
  text, clipboard contents, browser reads, and vision descriptions
  are all treated as data, never as instructions.
- A Point-and-Ask look mints what's called a LookGrant — one still
  image, one allow / deny prompt, then it stops. Printed
  instructions in a photo can never turn into an actual send.
- There's a loop cap on reasoning rounds (`agent.max_rounds` — 8
  normally, 32 in research mode, 16 when she is reading her own
  source / assessing the solar-system sim). Weather and SMS stay at 8.
  "Deeply research" is research mode even on the default fast chip.
  Empty chat after a long scrape asks her to write; it does not
  paste the page. `research_report` Findings are page excerpts with
  journal chrome stripped, not an LLM synthesis. Research may run 8
  distinct searches and open 16 distinct pages; `research_report`
  scrapes 8 sources by default and retries a shorter query if the
  first search is empty. The cap is a fuse.
  The real stop is the same successful tool+args this turn (same
  workspace list/read, same URL, same query). A new path still runs.
  Browser snapshots are not gated — the page can change.
- A house watch (`agent.watch`) rate-limits LAN ingest, locks a
  client after repeated bad tokens, and mutes outbound catalog /
  web calls if they spike. The chat model is not a security monitor;
  it can only read the snapshot via the `watch` tool. This is not
  antivirus and does not scan the rest of the PC.
- Every successful mutation gets appended to
  `data/action_ledger.jsonl`, kept for 14 days.
- Fat scrape/fetch bodies land in `data/tool_cache/` and expire after
  48 hours. The indexer does not treat the package, `tests/`, `docs/`,
  or `tool_cache` as papers to recall.
- Launch runs `arelis.housekeep`: scrape cache, ledger, spoken-reply
  wavs, old drops, stale logs, `turns.jsonl`, Chromium cache trees,
  and leftover `data/backups/memory-*.db`. Dated memory copies are
  off. Secrets, `memory.db`, rooms, and config are not touched. A full
  Chrome reset is `python -m arelis.housekeep --reset-browser`.
- CLI writes from a non-interactive session are denied unless you
  pass `--allow-write`.

Chat models always stay local, through Ollama — there's no paid
cloud chat API involved anywhere. Calendar APIs are the one explicit
cloud exception, documented in
[calendar-oauth.md](calendar-oauth.md). There's no silent SMS or mail
sending, and no captcha solver.

## Files that matter

`data/`, `logs/`, `outputs/`, and `models/` all live under the user
data root — `%LOCALAPPDATA%\Arelis` if installed, or the repository
itself if you're running from source. They should always be resolved
through `arelis/paths.py`; `tests/test_user_data_dir.py` enforces
this.

| Path | Why |
|---|---|
| `arelis/config/default.yaml` | Shipped defaults |
| `data/config.local.yaml` | Your overrides (gitignored) |
| `data/secrets.yaml` | Tokens (gitignored) |
| `data/profile.yaml` | Who you are and where you live |
| `data/rooms.yaml` | Your rooms |
| `data/jobs.yaml` | Scheduled jobs — hand-editable, paired with Task Scheduler entries at `\Arelis\<id>` |
| `arelis/jobs/` | Job storage, Windows task XML generation, the unattended runner |
| `arelis/physics/` | Reality's solar system |
| `arelis/earth/` | The Earth view — see [earth.md](earth.md) |
| `arelis/ui/earth_marks.py` | Drawn marks for Earth layers and solar object types |
| `arelis/ui/earth_globe/` | The Cesium globe (planet rendering only) |
| `arelis/ui/solar_gl.py` | Offscreen GL rendering for globes |
| `arelis/spatial/` | The world engine (source checkout only) |
| `outputs/physics/takes/` | Hand-tracking takes — if it's not saved in a take, it didn't happen |
| `data/memory.db` | Facts, goals, tasks |
| `data/backups/` | Unused; housekeep deletes leftover dated copies |
| `data/browser-profile/` | Her Chrome — caches pruned on launch; wipeable |
| `logs/` | See [telemetry.md](telemetry.md) |
| `outputs/` | Research, images, plots |

Any privacy claim made here can be checked directly against
`tests/test_egress.py`.
