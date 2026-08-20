# Logs

Where to look when something feels wrong. `logs/` is under the user data
root: `%LOCALAPPDATA%\Arelis\logs` for an installed copy, or the
repository root when running from source, where it is gitignored.
Nothing here is sent anywhere.

## Quick "what happened?"

| Question | File |
|----------|------|
| Why was that turn slow / which tools ran? | `logs/turns.log` plus `logs/turns.jsonl` |
| Did she enter JSON fallback or answer from a tool result? | Thinking dock. Also `logs/turns.jsonl` |
| Did a confirm / SMS / error fire on the bus? | `logs/events.log` |
| Are Ollama / calendar / SMS / mail up? | UI **Systems** menu (mail / SMS / calendar only show once connected). CLI `ready …` STATUS |
| App crash, IMAP, router, indexer exceptions | `logs/arelis.log` |
| Scheduled job mail digest | `logs/jobs.log` |
| Conversation mic stuck | `logs/voice.log` (wake decisions always. The rest needs `voice.debug: true`) |

## Files

**`logs/arelis.log`** (always on at UI / CLI / `--core` start). Root
logger, INFO, rotating 2 MB × 3. Exceptions, ingest warnings, model
rewarm, parked confirms, restored sends.

**`logs/turns.log`** (default on: `agent.turn_telemetry`). Stages per
turn: `start`, `preflight`, `ttft`, `ollama_metrics`, `round`, `tool`,
`confirm`, `exactness`, `done`. Each finished turn also appends one JSON
object to **`logs/turns.jsonl`**. That is the file to read when grading
a live session.

**`logs/events.log`** (default on: `agent.event_telemetry`). High-value
bus events only. Not token deltas or TTS clips.

**`logs/jobs.log`**: `--run-job` only.

**`logs/voice.log`**: wake decisions always (`wake_heard`, `wake_ack`,
`wake_drop`). Full state-machine vector when `voice.debug: true`.

Timestamps are local wall-clock. Match nearby lines across files by time
when ids do not join: `id=` (turn), `session=`, `span=` (STT), `eid=`
(bus), `confirm=` (card).

## Config knobs

| Key | Default | Effect |
|-----|---------|--------|
| `agent.turn_telemetry` | `true` | `turns.log` |
| `agent.event_telemetry` | `true` | `events.log` |
| `voice.debug` | `false` | Extra voice.log |
| `agent.auto_lessons` | `true` | Mines `turns.log` signatures into lessons |

## What is still not logged

- Full assistant token streams (thinking dock only. `events.log` keeps a
  240-char preview on ASSISTANT_DONE)
- Entire tool result bodies (400-char preview in `events.log`)
