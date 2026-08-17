# Voice wake and conversation listen

How idle wake is supposed to work. This is the behavior to keep when packaging
a version later — do not bump the version in this change; the operator chooses
the version and when it ships.

## Product rules

| You do | What happens |
|--------|----------------|
| Say **“Hey Arelis”** or **“Hey Arelis, …”** | Enter **conversation** (same as the two-arcs toggle). Remainder in the same clip is sent as the first turn. |
| Say a bare **“Arelis”**, “Hi Arelis”, “Okay Arelis”, or mention the name in passing | **No wake.** |

A match is a receipt, not a mystery: the two-arcs button latches on, flares
for a beat, and the composer/orbit says **listening**. After that it is the
normal talk pulse until you turn conversation off.

Every wake decision writes `logs/voice.log` even when `voice.debug` is off:
`wake_heard` (match or miss), `wake_ack` (UI receipt), `wake_drop` (clip
skipped because another was already in flight).

Conversation still stays on until you turn it off. This change only tightens
the phrase that gets you there.

## Phrase matching (`arelis/voice/wake.py`)

Required: **Hey** or Whisper’s **Hay**, then a tight name list
(`arelis`, `airelyse`, `aurelis`, `arrelis`, …). Mid-clip search is
greeting+name only. A clip that *starts* with Whisper’s **Pay** plus the
name also counts (`Pay a relus`); mid-clip “pay Aurelis” does not.
Cousins that match ordinary speech (`or Ellis`, `air Elise`) are not accepted.

Idle Whisper clips do **not** get `initial_prompt: "Hey Arelis."` — that prompt
was being echoed back from noise and counted as a wake
(`arelis/voice/stt.py`, purpose `wake`).

## Engines

- **whisper** (default until `models/wake/hey_arelis.onnx` exists): VAD →
  Whisper → `match_wake`.
- **openwakeword**: scores PCM only; a hit still enters conversation. Train on
  **“Hey Arelis” only**, not the bare name.

Porcupine is not in this tree.

## Code map

| File | Job |
|------|-----|
| `arelis/voice/wake.py` | Compound-phrase regex |
| `arelis/ui/voice_control.py` | WAKE / CONVERSATION / DICTATE |
| `arelis/ui/app.py` | `_on_wake_detected` → `set_conversation(True)` + `ack_wake` |
| `arelis/voice/telemetry.py` | `record_wake` always hits `logs/voice.log` |
| `arelis/voice/stt.py` | No wake-clip prompt seed |

## Shipping

Treat this as part of a later version bundle the operator names and pushes.
A private GitHub repo can take a **draft pull request** for review; nothing
here implies a version bump or a push.
