# Telemetry & logging map

Where to look when something feels wrong. `logs/` is under the user data root:
`%LOCALAPPDATA%\Arelis\logs` for an installed copy, or the repository root when
running from source, where it is gitignored. Nothing here is sent anywhere.

## Quick “what happened?”

| Question | File |
|----------|------|
| Why was that turn slow / which tools ran? | `logs/turns.log` + `logs/turns.jsonl` |
| Did a confirm / SMS / error fire on the bus? | `logs/events.log` |
| Are Ollama / calendar / SMS / mail up? | UI readiness strip (title bar); CLI `ready …` STATUS |
| App crash, IMAP, router, indexer exceptions | `logs/arelis.log` |
| Scheduled job mail digest | `logs/jobs.log` |
| Conversation mic state machine stuck | `logs/voice.log` (wake decisions always; the rest needs `voice.debug: true`) |
| Offline / live foundation matrix | `logs/foundation_bench.json` |
| VRAM / TTFT samples | `logs/utilization_bench.json` |
| Prefill/decode + gate table | `logs/latency_bench.json` |

## Files

### `logs/arelis.log` (always on at UI/CLI/`--core` start)

Root logger, INFO, rotating 2 MB × 3. Configured in `arelis/logging_setup.py`.
Exceptions, SMSGate/ingest warnings, model rewarm, parked confirms, restored
sends, unload failures.

### `logs/turns.log` (default on — `agent.turn_telemetry`)

Isolated logger `arelis.turn.trace`. Stages per turn: `start` (includes
`session=` when archive is attached), `preflight`, `ttft` (agent-felt first
painted token — not Ollama engine TTFT), `ollama_metrics` (per-round
`prompt_eval_count` / `prompt_eval_ms` / `eval_count` / `eval_ms`), `round`,
`tool` (includes `action=` for browser maps/search/read/reserve), `confirm`,
`exactness` (math / evidence / quote / dual_hit / sms_force /
scrape_after_search / refuse / pass), `done` (includes `model_prefill_ms` /
`model_decode_ms` when present). STT spans use `span=` ids.
Restored Allow sends also write a `restored_send` line.

Each finished turn also appends one JSON object to **`logs/turns.jsonl`**
(user preview, timings, tools, browser actions). That is the file to read
when grading a live session — no extra UI and no extra command for the
operator.

Cross-board suite: `scripts/bench_latency.py` (use `--mock` in CI).

```powershell
.\.venv\Scripts\python.exe scripts\bench_latency.py --num-ctx 8192
.\.venv\Scripts\python.exe scripts\bench_latency.py --num-ctx 8192 --repeat 3
.\.venv\Scripts\python.exe scripts\bench_latency.py --num-ctx 8192 --idle-s 120
```

Repeat summaries land in `logs/latency_bench_runs/`. Gate D requires a large
cold prefix; null equal-fast probes fail rather than pass. Hard gates also
include **C'** (tool open with seeded history, `<8s` round‑1) and **F**
(history growth plateau 16→32 turns). `history_window` lines in `turns.log`
show kept/dropped counts from the sliding window.

### `logs/events.log` (default on — `agent.event_telemetry`)

Isolated logger `arelis.event.audit`. High-value bus events only — not token
deltas or TTS clips. Includes user messages (preview), tool start/result,
confirm + reply, SMS received, model switch, errors, session load, filtered
STATUS lines, voice transcripts.

### `logs/jobs.log`

`--run-job` only (replaces root handlers). Rotating 2 MB × 5.

### `logs/voice.log`

Wake decisions (`wake_heard`, `wake_ack`, `wake_drop`) are always written, so
a missed “Hey Arelis” is countable without turning the rest of the loop into a
firehose. The full state-machine vector per transition is only attached when
`voice.debug: true`. Rotating 2 MB × 3. With debug on, the last few lines
usually explain a stuck mic.

## Correlation

| ID | Where |
|----|--------|
| `id=` on turn lines | Per-turn uuid (8 hex) in `turns.log` |
| `session=` | MemoryStore session id on turn `start` / `done` path |
| `span=` | STT / restored-send one-offs in `turns.log` |
| `eid=` | Bus event id prefix in `events.log` |
| `confirm=` | Confirm card id (park / reply / restored send) |

Timestamps are local wall-clock (`HH:MM:SS.mmm`). Match nearby lines across
files by time when ids do not join.

## Config knobs (`arelis/config/default.yaml`)

| Key | Default | Effect |
|-----|---------|--------|
| `agent.turn_telemetry` | `true` | `turns.log` |
| `agent.event_telemetry` | `true` | `events.log` |
| `voice.debug` | `false` | `voice.log` |
| `agent.auto_lessons` | `true` | Mines `turns.log` signatures into lessons |

## Mining

```powershell
.\.venv\Scripts\python.exe scripts\mine_lessons.py
# or --write to append catalog hits into data/lessons.yaml
```

## What is still not logged

- Full ASSISTANT_DELTA token streams (Thinking dock only; `events.log` now
  keeps a 240-char assistant preview on ASSISTANT_DONE)
- Entire tool result bodies (400-char preview in `events.log`; timing +
  action in `turns.jsonl`)
- Continuous VRAM sampling (manual `bench_utilization.py`)
- Operator E2E hardware smoke (headset / Notify) — not automatable here
