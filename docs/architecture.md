# How she is put together

Install and day-to-day stay in the [README](../README.md). Living notes
for this checkout: [whats-new.md](whats-new.md). This page is the map:
rooms, wiring, and which door she is not allowed through.

## This PC, then the rest

Everything she *thinks* stays here. The rest of the world is a tool call
you started, or a card you allowed.

You talk through the window, voice, the terminal, or the phone app.
The phone is a window onto this PC (same session). If the PC cannot be
reached, a small Gemma on the phone keeps talking until the house is
back, then those words copy in. That model is offered at pair as an
install (~2.6 GB): wait for Wi-Fi, or use mobile data on purpose.
Messages fly on a small event bus. The orchestrator runs one turn at a
time. The agent loop talks to Ollama and calls tools. Mail and texts do
not go out on a hope.

## First open

Not a tour. Two questions. The folder is a **permission**. The model is
a **recommendation**.

1. Start Arelis.
2. Which folder may she read, create, change, and delete?
3. She looks at graphics memory, RAM, and disk, and recommends one Qwen
   3.5 tag. Confirm it, or pick Gemma / DeepSeek.
4. If Ollama is missing, she downloads the official Windows engine into
   `%LOCALAPPDATA%\Arelis-runtime`, then pulls that tag plus
   `nomic-embed-text`.

That pins both composer chips to one tag in `config.local.yaml`. A copy
that already pinned `models.fast` is not asked again. Vision waits until
the first picture. Tags: [models.md](models.md).

## Every launch

She pins the chat model, then seeds Ollama's prefix cache
(`arelis/llm/startup.py`) with the persona, the tool policy, and the
full tool schema array — about 17,800 tokens, identical every turn.
Measured on a 12 GB card that seed is about 40 seconds once. After it, a
warm hello is about a second.

The window says **loading the model…** while the seed runs. It does not
say **thinking…** until a real turn has started. Sending while the seed
is still running waits on that work.

## One turn

1. Your text (or a voice transcript) hits the orchestrator. Typed and
   spoken share this path after the transcript exists.
2. The role model thinks. Tool schemas are already in the prompt from
   the launch seed. It may call tools.
3. Risky actions pause. A drive you already asked for does not. Mail and
   texts always do.
4. Tool results go back into the turn. She answers with what she actually
   got.

If she invents a number she cannot back up, finish gates can refuse
instead of sounding sure.

Native tool calling is the normal path. JSON fallback is only for when
Ollama rejects the tools array, or the first round is empty with no tool
yet. If a tool already succeeded this turn and the next round has empty
chat content, she answers from that result instead of entering JSON
mode. Writes and sends still wait.

The card headline is human: *text wife*, *write note.txt*. Deny is this
step only. Stop is the turn. Conversation mode (and a wake remainder)
hears allow, deny, stop, and spoken draft edits without starting a new
turn. After a stop, the next line is ordinary talk — she gets one note
that she was stopped. Idle wake stays deaf so Discord is not a decision.
**Settings → Allow** is the list. Mail, texts, and calendar never ride
along with **rest of this ask**.

A tiny ask (the time, a greeting, thanks, "who are you") still sends the
full schema array so the prefix cache stays intact. What it skips is the
unmatched web floor, the "call a tool first" hint, and holding the
answer until a tool round finishes — those turns stream. "Who is this"
(a photo, a fighter on TV) is not identity; it may still search. A place
("what time is it in Tokyo") still needs a tool. Unmatched real work
still fail-opens.

## Ways to run her

| How | When |
|-----|------|
| Window (`.\scripts\run_ui.ps1`) | Normal: chat, docks, Settings |
| CLI (`arelis --cli`) | Same brain in a terminal |
| Core (`.\scripts\run_core.ps1`) | Background: phone ingest, jobs, no window |
| Tray | Window hidden but still alive. The taskbar X and title close hide her; tray **Quit Arelis** is the real exit |

Core and UI talk over a small loopback bridge so inbound texts and
"open the window" still work when the window is closed.

## Window

Empty session is the orbit: warm void, a ring, a box under it. Typing
stays there until you send. Then you get the workbench: chat, composer,
docks.

| Piece | Job |
|-------|-----|
| Composer | Idle: centered prompt. Workbench: bottom row plus `fast` / `research` |
| Title strip | arelis, view, settings, window buttons |
| Readiness | Ollama chip and **Systems ▾**. Mail / SMS / calendar only appear there once connected |
| Chat stage | Orbit, streaming answer, Sources, allow / deny cards |
| Drive strip | Stop / Pause / your-turn while her browser is in flight |
| Thinking dock | Status, tools, rounds, and a wrapping think paragraph |
| Workspace dock | Roots, files, tool output |
| Camera dock | Webcam still. View → camera / Ctrl+5. In the `physics` room: Track / Record |
| History dock | Sessions, pending fact approve / reject |
| Notifications | Inbound SMS while the UI is open |
| Contacts | Named people for texts. View → contacts / Ctrl+6 |
| Calendar | Local tile, Ctrl+7. Month / week / day / agenda, plus **tasks** and **jobs**. Empty of Google events until you authorize |
| Settings | Audio / Window / Allow / Notify / Roots / Memory. Mail and calendar credentials are not a Settings tab: `data/secrets.yaml` and [calendar-oauth.md](calendar-oauth.md) |
| World plate | Floating stage. View → world / Ctrl+8. Only while the `physics` room is active **and** this copy is a source checkout (`world_stage_allowed`). Needs `pip install -e ".[spatial]"` for hands and `.[astro]` for REBOUND. Not in the installer. Default size 1280×800. Solar GPU path is `--solar-gl` / `ARELIS_SOLAR_GL=1` (offscreen FBO). Inspect-only WASD fly camera; H recites live keys; no craft chase-cam |

Settings → Window can fold unused panels after 30, 45, or 60 minutes
with no click, type, send, or wake word. Off by default. A turn, a card,
latched talk, or the Drive strip delays rest.

Inbound SMS flashes the taskbar if you are in another window. The phone
tile pulses when this process does not own the OS foreground.

The STATUS line about the Phone Notify URL lands in the thinking dock,
not chat. Painting it into chat used to hide the orbit on a cold launch.
Settings → Notify has the pairing QR.

## The brain

| Piece | Path | Job |
|-------|------|-----|
| Bus | `arelis/core/bus.py` | Events between UI and brain |
| Orchestrator | `arelis/core/orchestrator.py` | One turn at a time. Resumes the last room on launch |
| Agent loop | `arelis/core/agent_loop.py` | Model, tools, confirms, finish rules |
| Skills | `arelis/core/skills.py` | Which tools she leans on |
| Router | `arelis/llm/` | Pick the role model, warm, unload |
| Setup | `arelis/setup/` | First open: hardware, one model, pull |
| Startup | `arelis/llm/startup.py` | Pin the chat model, seed the prefix cache |
| Tools | `arelis/tools/` | Everything she can call |
| Jobs | `arelis/jobs/` | Unattended runner + Task Scheduler |
| Browser | `arelis/browser/` | Her Chrome |
| UI | `arelis/ui/` | Window, orbit, docks |
| Presence | `arelis/presence/` | Core, tray, IPC |
| Voice | `arelis/voice/` | Listen and speak. [voice-wake.md](voice-wake.md) |
| Spatial | `arelis/spatial/` | World engine, grant, takes. Pose is not a chat turn |
| Earth | `arelis/earth/` | Earth zone on the solar globe. ECEF store, simulated observatory, live public/keyed feeds (`feeds.py`). [earth.md](earth.md) |
| Config | `arelis/config/default.yaml` | Defaults. Overrides in `data/` |

Only one chat model sits in graphics memory. First open recommends one
tag from hardware and pins both chips to it, and sizes the context window
to the card it found. Shipped last-resort in `default.yaml` is
`qwen3.5:9b` for fast and research. Research is a deeper loop on the same
weights. File work stays on fast. That model sees images itself, so
`models.vision` is only a fallback for a chat model that cannot.
Tags: [models.md](models.md).

Persona text and the tool-policy block are byte-stable across turns.
Shipped config keeps the full tool schema array (`skill_tool_subset` and
`research_tool_subset` are false). A per-turn 6-tool subset was measured
and lost: the array sits near the front of the prompt, so shrinking it
blows the prefix cache and prefills ~17s every turn instead of ~3s after
one seed. `scripts/measure_tool_surface_prefill.py` is the receipt.
Startup pays the cold prefill once so the first chat turn does not.
Independent reads in the same round can run together. Writes and
pause-gated tools stay serial.

Two things still change the tools JSON on purpose: `send_sms` /
`send_email` are hidden unless this utterance asked to send (safety — a
greeting used to replay the last draft), and a room that lists `tools:`
cages the set. Leave that list off unless you mean it. If
`skill_tool_subset` is missing from a partial config, the loop defaults
it to **false**. Do not turn it on to "go faster".

## Tools (short)

Registered in `arelis/tools/__init__.py`. Scheduled jobs leave out send,
browser, vision, plot, document, solar, earth, the archive tools, and the other
tools that need a person present. `cas`, `units`, `catalog`, `python`,
and `calculator` may run unattended. [jobs.md](jobs.md).

`send_email` / `inbox`, `send_sms` / `inbound_sms`, and `agenda` are
registered only when mail, the phone, or a calendar source is actually
connected. Otherwise chat says she cannot.

| Tool | Plain English | Pause? |
|------|---------------|--------|
| `web_search` | Find pages | No |
| `scrape` / `web_fetch` | Read a page for her | No |
| `research_report` | Multi-source write-up under `outputs/research/` | No* |
| `browser` | Drive her Chrome | When she offers it. A drive you asked for is the grant |
| `workspace` | Files in allowed roots | Writes: yes |
| `analyze` / `doc_extract` / `git_info` | Tables, PDFs, git | No |
| `calculator` | Arithmetic | No |
| `python` | Short numerics cell (math / sympy / numpy). No files, no shell | No |
| `cas` / `units` | Closed forms, conversions, constants | No |
| `diagnostics` | Her own pytest suite. Source checkout with `tests/` | No |
| `tile` | Open or close a View-menu panel (thinking, calendar, world, …) | No |
| `plot` | PNG. Room → `plots/` in the project; orbit → `outputs/plots/` | Yes |
| `document` | PDF, Word, Excel, CSV, markdown. Room → `documents/` in the project; orbit → `outputs/documents/` | Yes |
| `catalog` | arXiv, Horizons; APOD / ADS after a free key | No |
| `solar` | Physics-room N-body (Horizons VECTORS + REBOUND IAS15). Source checkout. Approach/orbit, inspect-only fly camera, IAU spheres. Not landing | Yes |
| `earth` | Earth zone inside that lab: observer of published/broadcast contacts. Simulated unless `live`. Inventory in `feeds.py` (63 shipped / 9 keyed / 3 later / 4 out). Source checkout. [earth.md](earth.md) | No |
| `clipboard` / `ocr` / `vision` / `camera` | Paste, screen text, see an image, webcam | Yes (the still is free; seeing it pauses) |
| `memory` / `recall` / `tasks` / `goals` | Remember, chores, "what needs my attention" | Mutates: yes |
| `inbox` / `send_email` / `schedule` | Mail and timed jobs | Send: yes. Creating a job: yes. Inbox list is free; trash / archive / move / flags: yes |
| `send_sms` / `inbound_sms` | Text out / list inbound | Send: yes |
| `agenda` | Calendar | Writes: yes |
| `weather` / `user_location` | Forecast / where she thinks you are | No |
| `image` | New picture via local ComfyUI | Yes |
| `image_edit` | Resize and colour on a file that exists | Yes |
| `rooms` | Named project spaces | Create / change: yes |
| `contacts` | People for SMS | Mutates: yes |

\*Writes a local file. Outbound mail and SMS always need their own allow
/ deny and are never batched with other tools.

ComfyUI is a separate app. Arelis does not start it at launch. Shipped
`tools.image.auto_start` is false; if you set it true and point
`launch_cwd` at a Comfy install, the first **image** call may start it.
Until then, generating a picture reports unavailable rather than
launching something that is not there.

Scrape reads a URL for her, no window. `browser` moves her Chrome under
`data/browser-profile/`, not your daily Chrome. [browser-control.md](browser-control.md).

## Rooms

A room is a named place to work on one thing: its own thread, a folder,
a purpose she reads every turn. `/room physics` goes in. `/leave` comes
out. Launch resumes the last room you entered. The room id `physics` is
permanent: always present, forget refused, and the only place the World
plate and C920 tracking run.
[rooms.md](rooms.md).

## Jobs

A saved prompt, a time, and an email of the answer. Windows Task
Scheduler fires it; nobody is watching, so anything that would need
Allow is skipped and send/browser/vision are not registered. Mail must
already be connected or the job cannot run. Calendar tile → **jobs**, or
ask her to schedule it. [jobs.md](jobs.md).

## Memory and safety

- Chat history is a sliding window (`agent.history_max_messages`, shipped
  **120** — about 60 turns). The old 24-message cap dropped the front of
  the prompt long before the 65k window filled, which also blew the
  prefix cache. History dock: sessions plus pending fact approve / reject.
- Active facts live in `memory.db`. Manage them in Settings → Memory.
- Workspace roots are only folders you configure. Writes wait.
- Attachments stage copies under `data/drops/`.
- Loopback and LAN URLs are blocked for model-supplied fetches.
- Scrape, search, inbox, inbound SMS, OCR, clipboard, browser `read`,
  and vision are wrapped as data, not instructions.
- A Point-and-Ask look mints a LookGrant: one still, one allow / deny,
  then stop. Printed instructions cannot become a send.
- Loop cap: `agent.max_rounds` (8; research 12).
- Successful mutates append `data/action_ledger.jsonl`.
- Memory backups: dated copies in `data/backups/` for 14 days.
- CLI non-TTY writes are denied unless `--allow-write`.

Chat models stay local (Ollama). No paid cloud chat API. Calendar APIs
are the explicit cloud exception: [calendar-oauth.md](calendar-oauth.md).
No silent SMS or mail. No captcha solver.

## Files that matter

`data/`, `logs/`, `outputs/`, and `models/` are under the user data root:
`%LOCALAPPDATA%\Arelis` installed, the repository from source. Resolve
them through `arelis/paths.py`. `tests/test_user_data_dir.py` enforces
it.

| Path | Why |
|------|-----|
| `arelis/config/default.yaml` | Shipped defaults |
| `data/config.local.yaml` | Your overrides (gitignored) |
| `data/secrets.yaml` | Tokens (gitignored) |
| `data/profile.yaml` | Who and where you are |
| `data/rooms.yaml` | Your rooms |
| `data/jobs.yaml` | Scheduled jobs. Hand-editable. Paired with Task Scheduler `\Arelis\<id>` |
| `arelis/jobs/` | Store, Windows task XML, unattended runner |
| `arelis/physics/` | Solar lab: Horizons ICs, REBOUND, IAU WGCCRE attitude, equirectangular maps |
| `arelis/earth/` | Earth zone: ECEF observer plate, simulated layers, live public/keyed feeds. [earth.md](earth.md) |
| `arelis/ui/solar_gl.py` | Offscreen GL globes. Native GL widget aborted this AMD driver |
| `arelis/spatial/` | World engine (source checkout) |
| `outputs/physics/takes/` | Hand-tracking takes. If it is not in a take, it did not happen |
| `data/memory.db` | Facts, goals, tasks |
| `data/backups/` | Dated memory copies |
| `data/browser-profile/` | Her Chrome backpack |
| `logs/` | [telemetry.md](telemetry.md) |
| `outputs/` | Research, images, plots |

Privacy claims you can check: `tests/test_egress.py`.
