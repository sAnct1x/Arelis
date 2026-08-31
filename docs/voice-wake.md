# Voice

Talking and listening both come bundled in the Windows installer. If
you're running from a source checkout, you'll need
`pip install -e ".[voice]"` first.

There are exactly three listen modes — no fourth hiding somewhere:

| Control | Mode |
|---|---|
| **Hey Arelis**, or the two-arcs button / Ctrl+Shift+M | Conversation. She talks back. Say **goodbye** to hang up. |
| Mic button / Ctrl+M | Dictation into the composer. Doesn't send anything on its own. |
| Idle, after hangup | Wake-only. Deaf to ordinary speech, including a bare **Arelis**. |

## What actually happens when you say something

| You say | What happens |
|---|---|
| **Hey Arelis** or **Hey Arelis, what's the weather** | She enters conversation mode, same as pressing the two-arcs talk button. Anything after her name in that same clip counts as the first turn. |
| **Goodbye**, **that's all**, **stop listening**, **go to sleep** | She hangs up. Wake detection stays on in the background — just say **Hey Arelis** again when you want her back. Whatever room you were in stays put. |
| **Stop**, **be quiet**, **shut up** | She cuts off mid-turn. Works in conversation, on a one-shot wake, and while you are dictating — if a turn or a card is live. |
| **Pause**, **hold on** | Freezes her Chrome drive. The page stays. In Reality with no live drive, **pause** is still the sim. |
| **Go**, **resume**, **keep going** | Continues a held drive. After a stop, **keep going** is ordinary talk. |
| **Yes** / **no** (or **allow** / **deny**) | Resolves an open card — sodium paints it; filament (testing) hides it and the spoken ask is the grant. Deletes and Pay still wait for this. |
| A bare **Arelis**, **Hi Arelis**, **Okay Arelis**, or her name mentioned in passing | Nothing happens. Those trigger too easily during a call or while you're just talking in a room. |

A real match is meant to be unmistakable: the talk button latches on,
flares briefly, and the composer or empty session shows **listening**.
From there it's just ordinary conversation until you say goodbye (or
toggle the button / Ctrl+Shift+M). If an allow / deny card is up on
screen, the mic stays live specifically for **allow** or **deny** —
anything else gets ignored, including a hangup attempt, until you've
actually decided on the card.

Conversation speech-to-text runs on Sherpa-ONNX Zipformer, not
Whisper. The default pack is Kroko 2025 (mixed case, with
punctuation); the 2023 LibriSpeech pack is the fallback if Kroko
isn't available. Sherpa has a habit of mishearing mail-related words
— "email" sometimes comes out as a French-sounding name, "inbox" as
two separate words. Those get quietly repaired so the email skill
actually sees what you meant to say. Wake-word matching runs on a
completely separate engine and doesn't get this same repair pass.

The end of an utterance is detected with a short Silero pause
combined with Pipecat Smart Turn v3, whenever `models/smart_turn/` is
present (or gets downloaded on first run — about 8 MB). If that ONNX
file is missing, she just falls back to longer silence windows
instead.

The first time you use speech output, Kokoro-82M may need to download
(~300 MB) into `models/kokoro/`. The first conversation may similarly
need to pull the Kroko Zipformer pack into `models/sherpa/` if it
isn't already there. Both speech-to-text and text-to-speech run on
the CPU — the GPU stays dedicated to Ollama.

If you're on a headset, talking over her counts as the start of a new
turn: she stops talking, and whatever you said becomes the question.
On speakers, you'll want `conversation.barge_in_as_turn: false` set,
so a clip that picks up both her voice and yours stays control-only
(interpreted as stop / allow / deny rather than a new question).

Every wake and conversation decision gets logged to `logs/voice.log`,
even with `voice.debug` turned off — things like `wake_heard`,
`wake_ack`, `wake_drop`, `barge_in`, `smart_turn`,
`utterance_dropped`. The full raw VAD firehose only gets written when
`voice.debug` is actually set to true.

## Phrase matching (`arelis/voice/wake.py`)

A wake requires **Hey** (or Whisper's occasional mishearing of it as
**Hay**), followed by a tight list of accepted name variants —
arelis, airelyse, aurelis, arrelis, and a few others in that vein.
Mid-clip matching only looks for the greeting plus the name together.
A clip that opens with Whisper's **Pay** plus her name also counts
("Pay a relus," as odd as that sounds) — but that same "pay Aurelis"
phrasing mid-clip does not count. Near-miss cousins that overlap with
normal speech — "or Ellis," "air Elise" — are deliberately not
accepted.

Idle Whisper clips are never given the `initial_prompt: "Hey Arelis"`
hint, on purpose — that prompt was actually getting echoed back out
of background noise and registering as a false wake.

## Engines involved

| Job | Engine |
|---|---|
| Idle wake (**Hey Arelis**) | faster-whisper until `models/wake/hey_arelis.onnx` exists, then openwakeword running on that ONNX. Whatever's left in the same audio clip becomes the first turn. |
| Voice activity detection | Silero VAD |
| End of turn | Smart Turn v3, after a short pause — or a fixed `silence_ms` if that ONNX file is missing |
| Conversation + dictation (Ctrl+M) | Sherpa-ONNX Kroko Zipformer, on live PCM audio. Falls back to the 2023 pack or faster-whisper if Kroko isn't available |
| Speech output | Kokoro-82M (`af_heart` voice) — the first punctuated sentence can start playing before the rest of the answer has even finished generating. Falls back to Piper Jenny if Kokoro can't run |

If you're training your own wake model, train it on **Hey Arelis**
specifically, not the bare name alone. The openwakeword package is
kept as an optional extra simply because there's no freely
downloadable `hey_arelis.onnx` out there to bundle.

Porcupine isn't used anywhere in this codebase, for what it's worth.

## Code map

| File | Job |
|---|---|
| `arelis/voice/wake.py` | The compound-phrase matching regex |
| `arelis/voice/openwake.py` | Optional ONNX-based wake detection, once `models/wake/hey_arelis.onnx` exists |
| `arelis/ui/voice_control.py` | Manages WAKE / CONVERSATION / DICTATE states |
| `arelis/ui/app.py` | `_on_wake_detected` latches into conversation mode |
| `arelis/voice/telemetry.py` | `record_always` / `record_wake` — always writes to `logs/voice.log` |
| `arelis/voice/stt.py` | No prompt-seeding on wake clips; mail-word repair applied during conversation and dictation |
| `arelis/voice/sherpa_stt.py` | The live Kroko session, with the 2023 pack as fallback |
| `arelis/voice/smart_turn.py` | Pipecat Smart Turn v3 ONNX |
| `arelis/voice/whisper_mel.py` | Whisper-compatible mel spectrogram, used for Smart Turn |
| `arelis/voice/speech_text.py` | Extracts the first punctuated sentence for TTS to start on |
| `arelis/voice/kokoro_tts.py` | Kokoro-82M (`af_heart`), running on CPU |
| `arelis/voice/vad.py` / `silero_vad.py` | Live speech onset and end-point detection |
