# Voice wake and conversation listen

How to start talking without touching the keyboard, and what she will
not treat as a wake.

Talking and listening are included in the Windows installer. From a
source checkout they need `pip install -e ".[voice]"`.

Three listen modes. There is not a fourth.

| Control | Mode |
|---------|------|
| **Hey Arelis**, or the two-arcs button / **Ctrl+Shift+M** | Conversation. She talks back. Say **goodbye** to hang up. |
| Mic button / **Ctrl+M** | Dictate into the composer. Does not send. |
| Idle, after hangup | Wake only. Deaf to ordinary speech, including a bare **Arelis**. |

## What you do

| You say | What happens |
|--------|----------------|
| **Hey Arelis** or **Hey Arelis, what's the weather** | She enters conversation, the same as pressing the two-arcs talk button. Anything after the name in the same clip is the first turn. |
| **goodbye**, **that's all**, **stop listening**, **go to sleep** | She hangs up. Wake stays on. Say Hey Arelis when you want her again. The room you were in stays put. |
| **stop**, **be quiet**, **shut up** | She cuts the turn and stays in the call. |
| A bare **Arelis**, "Hi Arelis", "Okay Arelis", or her name in passing | Nothing. Those fire too easily on a call or in a room. |

A match is meant to be obvious: the talk button latches on, flares for a
beat, and the composer or orbit says **listening**. After that it is
ordinary conversation until you say **goodbye** (or toggle the button /
Ctrl+Shift+M). If an allow / deny card is up, the mic stays on: say
**allow** or **deny**. Anything else is ignored, including hangup, until
the card is decided.

Conversation STT is Sherpa-ONNX Zipformer, not Whisper. The default pack
is Kroko 2025 (mixed-case, punctuation). The 2023 LibriSpeech pack is the
fallback if Kroko is missing. Sherpa often hears mail words as a French
name or a split (`emile` for email, `in box` for inbox). Those are
repaired so the email skill sees the words you said. Wake matching is a
separate engine and does not use that repair.

End of an utterance is a short Silero pause plus Pipecat Smart Turn v3
when `models/smart_turn/` is present (or first-run download, ~8 MB).
Missing that ONNX keeps the longer silence windows.

First speak may download Kokoro-82M (~300 MB) into `models/kokoro/`.
First conversation may download the Kroko Zipformer pack into
`models/sherpa/` if it is not there. STT and TTS stay on CPU. The GPU is
for Ollama.

Headset barge-in is the next turn (she stops talking, then your clip is
the question). Speakers: set `conversation.barge_in_as_turn: false` so
the mixed clip stays control-only (stop / allow / deny).

Every wake and conversation decision is written to `logs/voice.log` even
when `voice.debug` is off: `wake_heard`, `wake_ack`, `wake_drop`,
`barge_in`, `smart_turn`, `utterance_dropped`. The VAD firehose only
lands in that file when `voice.debug` is true.

## Phrase matching (`arelis/voice/wake.py`)

Required: **Hey** or Whisper's **Hay**, then a tight name list
(`arelis`, `airelyse`, `aurelis`, `arrelis`, …). Mid-clip search is
greeting plus name only. A clip that starts with Whisper's **Pay** plus
the name also counts (`Pay a relus`). Mid-clip "pay Aurelis" does not.
Cousins that match ordinary speech (`or Ellis`, `air Elise`) are not
accepted.

Idle Whisper clips do not get `initial_prompt: "Hey Arelis."` That
prompt was being echoed back from noise and counted as a wake.

## Engines

| Job | Engine |
|-----|--------|
| Idle wake "Hey Arelis" | faster-whisper until `models/wake/hey_arelis.onnx` exists. Then openwakeword on that ONNX. Remainder of the same clip is the first turn. |
| Voice activity | Silero VAD |
| End of turn | Smart Turn v3 after a short pause. silence_ms if the ONNX is missing. |
| Conversation + dictate (`Ctrl+M`) | Sherpa-ONNX Kroko Zipformer (live PCM). 2023 pack or faster-whisper if Kroko is missing. |
| Speech out | Kokoro-82M `af_heart`. First punctuated sentence can play before the answer is finished. Piper Jenny if Kokoro cannot run. |

Train a wake ONNX on **Hey Arelis** only, not the bare name. The
openwakeword package is an optional extra because there is no free
`hey_arelis.onnx` to download.

Porcupine is not in this tree.

## Code map

| File | Job |
|------|-----|
| `arelis/voice/wake.py` | Compound-phrase regex |
| `arelis/voice/openwake.py` | Optional ONNX wake when `models/wake/hey_arelis.onnx` exists |
| `arelis/ui/voice_control.py` | WAKE / CONVERSATION / DICTATE |
| `arelis/ui/app.py` | `_on_wake_detected` latches conversation |
| `arelis/voice/telemetry.py` | `record_always` / `record_wake` always hits `logs/voice.log` |
| `arelis/voice/stt.py` | No wake-clip prompt seed. Mail-word repair on conversation and dictate |
| `arelis/voice/sherpa_stt.py` | Live Kroko session; 2023 pack fallback |
| `arelis/voice/smart_turn.py` | Pipecat Smart Turn v3 ONNX |
| `arelis/voice/whisper_mel.py` | Whisper-compatible mel for Smart Turn |
| `arelis/voice/speech_text.py` | First punctuated sentence for TTS |
| `arelis/voice/kokoro_tts.py` | Kokoro-82M `af_heart` on CPU |
| `arelis/voice/vad.py` / `silero_vad.py` | Live onset / end-point |
