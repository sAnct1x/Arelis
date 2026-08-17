# How Arelis works

Install and day-to-day stay in the [README](../README.md).

## Big picture

```mermaid
flowchart TB
  you[You]
  surfaces[Glass_UI_CLI_Voice_Phone]
  bus[Event_bus]
  brain[Orchestrator_agent_loop_Ollama]
  tools[Tool_registry]
  world[Files_Web_HerChrome_Mail_SMS_Calendar]
  you --> surfaces --> bus --> brain --> tools --> world
```

You talk through a surface. Messages fly on an **event bus**. The **brain**
(orchestrator + agent loop + Ollama) decides what to say and which **tools** to
call. Tools reach the outside world.

## One turn

```mermaid
flowchart LR
  msg[Your_message]
  orch[Orchestrator]
  model[Ollama_model]
  tool[Tool_call]
  allow{Needs_Allow}
  you[You_tap_Allow]
  ans[Answer]
  msg --> orch --> model
  model -->|maybe| tool
  tool --> allow
  allow -->|yes| you --> tool
  allow -->|no| tool
  tool --> model --> ans
```

1. Your text (or voice transcript) hits the orchestrator.
2. The role model thinks — maybe it calls tools.
3. Risky actions pause for **Allow**.
4. Tool results go back into the turn; she answers with what she actually got.

If she invents a number or claim she cannot back up, finish gates can **refuse**
instead of sounding sure.

## Ways to run her

| How | When |
|-----|------|
| Glass UI (`.\scripts\run_ui.ps1`) | Normal — chat, docks, Settings |
| CLI (`arelis --cli`) | Same brain in a terminal |
| Core (`.\scripts\run_core.ps1`) | Background: phone ingest, jobs; no glass |
| Tray | UI hidden but still alive |

Core and UI talk over a small loopback bridge so inbound texts and “open the
window” still work when the glass is closed. Presence lives under
`arelis/presence/`.

## Glass UI

Empty session is the **orbit idle** face (`arelis/ui/void_idle.py`): warm void,
orbit ring, prompt under the orbit. The face stays locked to the window bloom
while idle. Typing stays there — the field grows and wraps; Enter sends
(Shift+Enter = newline). Once there is a thread (or Allow / voice / a busy
turn), the **workbench** shows the transcript and a bottom composer. A smaller
dim orbit parks in the bottom-right.

While she drives **her** Chrome, a glass **Drive strip** sits above the
composer: **Arelis Chrome**, a status line (`about to click e3…`, `your turn —
captcha`), **Pause / Go**, **Stop**. Chrome itself stays looking like Chrome.

| Piece | Job |
|-------|-----|
| Composer | Idle: centered growing prompt. Workbench: bottom row + role picker (`fast` / `research` / `code`) |
| Title strip | **arelis** · view · settings · window buttons |
| Readiness | **Ollama** chip + **Systems ▾** (model pin, Allow gates, calendar / SMS / mail). Pulses when a confirm card is open |
| Chat stage | Orbit idle or streaming answer, Sources, Allow cards |
| Drive strip | Stop / Pause / your-turn while a browser tool is in flight |
| Thinking dock | Trace / status (model, tools) |
| Workspace dock | Roots, browse, open/save, editor, tool output |
| Camera dock | Webcam still → Point-and-Ask (LookGrant). View → camera / Ctrl+5 |
| History dock | Sessions; pending fact approve/reject |
| Notifications dock | Inbound SMS while the UI is open |
| Settings | Audio / Window / Notify / Roots / Memory |

Docked instruments are type in the void (no fill plate). Floating tiles are
opaque — a translucent HWND composites chat through the plate (“ghost chat”).
Launch redocks saved floats.

## The brain (code map)

| Piece | Path | Job |
|-------|------|-----|
| Bus | `arelis/core/bus.py` | Events between UI and brain |
| Orchestrator | `arelis/core/orchestrator.py` | One turn at a time; attachments |
| Agent loop | `arelis/core/agent_loop.py` | Model ↔ tools, confirms, finish rules |
| Skills / preflight | `arelis/core/skills.py`, `preflight.py`, `intent_catalog.py`, `look.py` | Weighted skill cards, one intent table, LookGrant |
| Router | `arelis/llm/` | Pick role model, warm/unload |
| Tools | `arelis/tools/` | Everything she can call |
| Browser | `arelis/browser/` | Her Chrome: launch, drive, walls, maps, search |
| UI | `arelis/ui/` | Void window, orbit, docks, Drive strip |
| Presence | `arelis/presence/` | Core, tray, IPC, readiness |
| Voice | `arelis/voice/` | STT + Kokoro/Piper TTS. Idle wake is **Hey Arelis** (compound phrase), then conversation. See [voice-wake.md](voice-wake.md). |
| Config | `arelis/config/default.yaml` | Defaults (overrides in `data/`) |

Only **one** chat model is meant to be in VRAM. Roles: `fast` (7B), `research`
(14B), `code` (coder 7B). Static system prefix is persona + `SKILL_CORE`
(byte-stable). Pure chat can skip tool schemas (`chat_fast_path`). Everyday
turns may shrink the tools array to matched skill cards
(`agent.skill_tool_subset`). Skill selection is weighted (phrases over tokens,
generic words demoted, negative hints veto a card); unmatched turns still fail
open. Same-round independent READ calls can run together
(`agent.read_fanout`); writes and Allow-gated tools stay serial.

## Tools (short)

Registered in `arelis/tools/__init__.py`. Scheduled jobs leave out SMS/browser
on purpose.

| Tool | Plain English | Allow? |
|------|---------------|--------|
| `web_search` | Find pages (DuckDuckGo) | No |
| `scrape` / `web_fetch` | Read a page or raw HTTP **for her** | No |
| `research_report` | Multi-source write-up under `outputs/research/` | No* |
| `browser` | Drive **her** Chrome window | Yes |
| `workspace` | List / read / write files in allowed roots | Writes: yes |
| `analyze` / `doc_extract` / `git_info` | Tables, PDFs, git status | No |
| `calculator` | Exact math | No |
| `clipboard` / `ocr` / `vision` / `camera` | Paste, screen text, see an image, webcam still | Yes (camera snapshot is not Allow; seeing is) |
| `memory` / `recall` / `tasks` / `goals` | Remember, chores, commitments; also answer "what needs my attention" | Mutates: yes |
| `inbox` / `send_email` / `schedule` | Read mail; send; timed digests | Send/schedule: yes |
| `send_sms` / `inbound_sms` | Text out / list inbound | Send: yes |
| `agenda` | Calendar list/sync/create | Writes: yes |
| `weather` / `user_location` | Forecast / where she thinks you are | No |
| `image` | Generate a new picture via local ComfyUI | Yes |
| `image_edit` | Resize / crop / vibrance on a file that exists (Pillow, no model) | Yes |
| `contacts` | Named people for SMS | Mutates: yes |

\*Writes a local artifact; still logged. Outbound mail/SMS always need their own
Allow and are never batched with other tools.

### Browser vs scrape

Scrape reads a URL **for her** (no window). `browser` moves **her** Chrome
(`data/browser-profile/`), not your daily Chrome. You watch that window.

| Action | What it does |
|--------|----------------|
| `open` / `navigate` | Land a URL or alias in her window |
| `snapshot` | Click refs (buttons / links / fields) |
| `read` | Compact text of the tab she is on (untrusted) |
| `maps` | Google Maps directions + a phone-ready link |
| `search` | Google / YouTube / Amazon results in her window |
| `reserve` | OpenTable / Resy / Google — party/date/time in the URL; you click Book |
| `click` / `type` / `scroll` / `press` / `select` / `wait` | Drive like a person. Glow, then click. No passwords / OTP |
| `screenshot` | PNG under `outputs/images/` — then `vision` separately |
| `tabs` / `relaunch` | List/select tabs; restart **her** profile only |

A glass Drive strip is the cockpit. Captcha, sign-in, and Book / Pay / Checkout
freeze the drive — she does not solve puzzles or click the last button. Add to
cart is allowed. Reservations fill party / date / time; you click Book.
[browser-control.md](browser-control.md).

## Rooms

A **room** is a named place to work on one thing — its own conversation thread,
one workspace project, a purpose she is given every turn, and a model lean.
`/room physics` or "let's work on physics" goes in; `/leave` comes out. The
general conversation stays forgettable; rooms are where the work that lasts
lives. Definitions in `data/rooms.yaml`, threads in `memory.db` tagged with the
room. Full surface: [rooms.md](rooms.md).

## Memory and safety

- **Chat history** — sliding window (`agent.history_max_messages` = 24). History
  dock: sessions plus pending fact approve/reject.
- **Active facts** — `memory.db`; manage / forget in Settings → Memory.
- **Workspace roots** — only folders you configure. Writes go through Allow.
- **Attachments** — paperclip / drag-drop stages copies under `data/drops/`.
- **Private URLs** — loopback / LAN blocked for model-supplied fetches.
- **Untrusted fetches** — scrape / web_fetch / search / inbox / inbound SMS /
  OCR / clipboard / browser `read` / vision are wrapped as *data, not instructions*.
  A later send or write in the same turn notes that on the Allow card.
  A Point-and-Ask look mints a LookGrant (`can_act=false`): one still, one
  Allow, then stop — printed instructions cannot become a send.
- **Loop cap** — `agent.max_rounds` (default 8; research 12).
- **Ollama mid-turn death** — short line in chat; exception in Thinking.
- **Action ledger** — successful mutates append `data/action_ledger.jsonl`.
- **Memory backup** — dated copy in `data/backups/` (keeps 14 days).
- **CLI** — non-TTY writes denied unless `--allow-write`.

### Locks we keep on purpose

- Chat models stay **local** (Ollama). No paid cloud chat API.
- Calendar **APIs** (Google / Outlook) are the explicit cloud exception —
  [calendar-oauth.md](calendar-oauth.md). Tokens in gitignored `data/secrets.yaml`.
- No silent SMS or mail. No multi-agent swarm.
- No captcha solver. Co-op: she freezes, you tap, she continues.

## Files that matter

`data/`, `logs/`, `outputs/` and `models/` throughout these docs are relative to
the user data root, which is `%LOCALAPPDATA%\Arelis` for an installed copy and the
repository itself when running from source. Nothing mutable is ever written beside
the code: `site-packages` is unwritable for a standard user, is replaced by an
update, and is shared by every account on the machine. Resolve these through
`arelis/paths.py` rather than from the package location — `tests/test_user_data_dir.py`
enforces it.

Only `arelis/…` paths below are part of the installation.

| Path | Why |
|------|-----|
| `arelis/config/default.yaml` | Shipped defaults |
| `data/config.local.yaml` | Your overrides (gitignored) |
| `data/secrets.yaml` | Tokens (gitignored) |
| `data/profile.yaml` | Who/where you are |
| `data/rooms.yaml` | Your rooms — [rooms.md](rooms.md) |
| `data/memory.db` | Facts, goals, tasks |
| `data/backups/` | Dated `memory-YYYYMMDD.db` copies |
| `data/browser-profile/` | Her Chrome backpack |
| `logs/` | `arelis.log`, turns, events — [telemetry.md](telemetry.md) |
| `outputs/` | Research reports, images |

## Want more detail?

| Topic | Doc |
|-------|-----|
| Rooms | [rooms.md](rooms.md) |
| Voice wake / listen | [voice-wake.md](voice-wake.md) |
| Models / VRAM | [models.md](models.md) |
| Browser | [browser-control.md](browser-control.md) |
| Phone texts | [notify-inbound.md](notify-inbound.md) |
| Calendar login | [calendar-oauth.md](calendar-oauth.md) |
| Logs | [telemetry.md](telemetry.md) |
| Working on Arelis | [CONTRIBUTING.md](../CONTRIBUTING.md) |
