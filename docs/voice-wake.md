# Voice wake and conversation listen

How to start talking to Arelis without touching the keyboard, and what she
will not treat as a wake.

Talking and listening are included in the Windows installer. From a source
checkout they need `pip install -e ".[voice]"`.

## What you do

| You say | What happens |
|--------|----------------|
| **“Hey Arelis”** or **“Hey Arelis, what’s the weather”** | She enters conversation, the same as pressing the two-arcs talk button. Anything after the name in the same clip is the first turn. |
| A bare **“Arelis”**, “Hi Arelis”, “Okay Arelis”, or her name in passing | **Nothing.** Those fire too easily on a call or in a room. |

A match is meant to be obvious: the talk button latches on, flares for a beat,
and the composer or orbit says **listening**. After that it is ordinary
conversation until you turn it off. Conversation stays on until you turn it
off; wake is only how you get there. If an allow / deny card is up, the mic
stays on: say **allow** or **deny**. Anything else is ignored — it is not a
new question.

Conversation STT is **Sherpa-ONNX Zipformer**, not Whisper. Sherpa often hears
mail words as a French name or a split (`emile` / `emiles` / `emil` for email,
`in box` for inbox). Those are repaired in `scrub_transcript` so inbox
preflight and the email skill see the words you said. Wake matching is a
separate engine and does not use that repair.

Every wake decision is written to `logs/voice.log` even when `voice.debug` is
off: `wake_heard` (match or miss), `wake_ack` (the UI receipt), `wake_drop`
(a clip skipped because another was already in flight). The rest of the voice
state machine only lands in that file when `voice.debug: true`.

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

| Job | Engine |
|-----|--------|
| Idle wake “Hey Arelis” | faster-whisper until `models/wake/hey_arelis.onnx` exists (title: `Listening for Hey Arelis (whisper)`). Then **openwakeword** on that ONNX. |
| Voice activity | Silero VAD |
| Conversation + **dictate** (`Ctrl+M`) | Sherpa-ONNX Zipformer EN (`voice.stt.backend: sherpa`) |
| Speech out | Kokoro-82M `af_heart`; Piper Jenny if Kokoro cannot run |

- **whisper** (wake, until the ONNX exists): VAD → Whisper → `match_wake`.
- **openwakeword**: scores PCM only; a hit still enters conversation. Train on
  **“Hey Arelis” only**, not the bare name. The package is an optional extra
  because there is no free `hey_arelis.onnx` to download.

Porcupine is not in this tree.

## Code map

| File | Job |
|------|-----|
| `arelis/voice/wake.py` | Compound-phrase regex |
| `arelis/ui/voice_control.py` | WAKE / CONVERSATION / DICTATE |
| `arelis/ui/app.py` | `_on_wake_detected` → `set_conversation(True)` + `ack_wake` |
| `arelis/voice/telemetry.py` | `record_wake` always hits `logs/voice.log` |
| `arelis/voice/stt.py` | No wake-clip prompt seed; `repair_stt_mail_words` on conversation/dictate |
