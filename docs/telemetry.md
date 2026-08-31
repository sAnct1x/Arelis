# Logs

Where to look when something feels wrong. `logs/` is under the user data
root: `%LOCALAPPDATA%\Arelis\logs` for an installed copy, or the
repository root when running from source, where it is gitignored.
Nothing here is sent anywhere.

## Quick "what happened?"

| Question | File |
|----------|------|
| Why was that turn slow / which tools ran? | `logs/turns.log` plus `logs/turns.jsonl` |
| Did the first chat token wait on the prefix seed? | Thinking dock: **loading the model…**. Also `logs/turns.jsonl` → `model_prefill_ms` after a turn |
| Did she enter JSON fallback or answer from a tool result? | Thinking dock. Also `logs/turns.jsonl` |
| Did a confirm / SMS / error fire on the bus? | `logs/events.log` |
| Are Ollama / calendar / SMS / mail up? | UI **house ▾** (mail / SMS / calendar only show once connected). CLI `ready …` STATUS |
| Did ingest lock a client / mute outbound APIs? | UI **house ▾ → Watch**. STATUS lines starting `Watch:`. `logs/events.log` |
| App crash, IMAP, router, indexer exceptions | `logs/arelis.log` |
| Scheduled job mail digest | `logs/jobs.log` |
| Conversation mic stuck | `logs/voice.log` (wake, barge-in, Smart Turn, dropped utterances always. `voice.debug: true` for the VAD firehose) |
| Did that chat turn re-prefill the whole prompt? | `logs/turns.jsonl` → `model_prefill_ms`, `prompt_eval_count` |
| Reality plate / Earth live / hitch | `logs/reality.log` plus `logs/reality.jsonl` |
| Reality plate / hands hitch (GL crash) | `logs/solar_gl.log`. Hands takes under `outputs/physics/takes/` |
| Hands session (pose, click, grab, miss) | `logs/hands.log` plus `logs/hands.jsonl` |
| Reality solar receipt (IAS15 state, not a screenshot) | `outputs/physics/solar/<utc>/` (`manifest.json` + `state.jsonl`) |

## Files

**`logs/arelis.log`** (always on at UI / CLI / `--core` start). Root
logger, INFO, rotating 2 MB × 3. Exceptions, ingest warnings, model
rewarm, parked confirms, restored sends.

**`logs/turns.log`** (default on: `agent.turn_telemetry`). Stages per
turn: `start`, `preflight`, `ttft`, `ollama_metrics`, `round`, `tool`,
`confirm`, `exactness`, `done`. Logged `ttft` is first painted chat
token, not Ollama engine TTFT. Tool-bearing turns hold paint, so that
number includes the tool rounds. Each finished turn also appends one JSON
object to **`logs/turns.jsonl`**. That is the file to read when grading
a live session.

**`logs/events.log`** (default on: `agent.event_telemetry`). High-value
bus events only. Not token deltas or TTS clips.

**`logs/jobs.log`**: `--run-job` only. Job definitions live in
`data/jobs.yaml` (not a log). [jobs.md](jobs.md).

**`logs/voice.log`**: conversation decisions always (`wake_heard`,
`wake_ack`, `wake_drop`, `barge_in`, `barge_turn`, `barge_control`,
`smart_turn`, `utterance_dropped`, `listen_resume`, `wake_remainder`).
Full state-machine vector when `voice.debug: true`. `tts_first` and live
`stt` spans land in `turns.log` when turn telemetry is on.

**`logs/hands.log`** and **`logs/hands.jsonl`** (always on while a hands
session is live). Session start/stop, 1 Hz pose sample, click / click_miss /
click_hit, grab / drop / flick, scroll, span_edge. Numbers only — no
frames. Pytest writes nothing unless a test points
`arelis.spatial.hands_log` at a temp dir.

**`logs/reality.log`** and **`logs/reality.jsonl`** (always on while we
tune Reality). Enter/leave Earth, band changes, live merge, each
adapter (ms / n / err), OpenSky spend, land/OSM/buildings fetches, travel, lock,
look-from (id/kind/media only — never a URL), dumps, overlay chips,
Cesium host ready/failed (photoreal miss is not a host fail),
and a 1 Hz paint sample (ms, band, n). Pytest writes nothing unless a
test points the module at a temp dir. Clean this firehose up once the
plate is right. `arelis/physics/telemetry.py`. Stream URLs never land
here.

Timestamps are local wall-clock. Match nearby lines across files by time
when ids do not join: `id=` (turn), `session=`, `span=` (STT), `eid=`
(bus), `confirm=` (card).

## Config knobs

| Key | Default | Effect |
|-----|---------|--------|
| `agent.turn_telemetry` | `true` | `turns.log` |
| `agent.event_telemetry` | `true` | `events.log` |
| `agent.watch.enabled` | `true` | Inbound rate limit, bad-token lockout, outbound API mute |
| `voice.debug` | `false` | Extra VAD ticks in voice.log. Decisions still write. |
| `agent.auto_lessons` | `true` | Mines `turns.log` signatures into lessons |

## What is still not logged

- Full assistant token streams (thinking dock only. `events.log` keeps a
  240-char preview on ASSISTANT_DONE)
- Entire tool result bodies (400-char preview in `events.log`)
- Phone Gemma latency while the house is away
- Look-from stream URLs (deliberate; pin stays honest)

**`outputs/physics/solar/`** is not a log. Leaving Reality writes a
cited snapshot of the live IAS15 state (ECLIPJ2000 metres) so a figure can
be the same integrator, not a PNG. `solar action=dump` does the same
without leaving. Leaving Earth writes `outputs/physics/earth/<utc>/`
the same way. Hands takes stay under `outputs/physics/takes/`.
No GL still in that bundle yet.
