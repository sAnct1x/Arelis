# Models

Arelis thinks with models that live on your machine, through
[Ollama](https://ollama.com/download). Nothing is sent to a paid API. Only
**one** chat model is hot at a time. The rest of what this checkout changed
is in [whats-new.md](whats-new.md).

Ollama is **system-wide**. The live installer (currently **0.2.2**) and a
source checkout share the same `ollama` tags. Do not `ollama rm` a tag the
installed app still names.

## 18 Aug 2026 — checkout try (not a release)

No version bump. This checkout dropped the **code** role: file/git/debug
asks stay on `fast` plus workspace/code skills. Shipped
`arelis/config/default.yaml` still names the 0.2.2 Qwen2.5 **fast** and
**research** tags (no `models.code`). This checkout overlays
`data/config.local.yaml`:

| Role | Tag | What it actually is |
|------|-----|---------------------|
| `fast` | `qwen3.5:9b` | Day driver. Thinking **on** (~5 s to first paint). File/git work stays here. |
| `research` | `qwen3.5:9b` | **Same weights**, thinking on. Deeper loop: more rounds, dual web hits, research tool subset, `num_ctx` 16384. |
| `vision` | `qwen2.5vl:3b` | Unchanged. Unload chat, one shot, pin fast again. |
| embed | `nomic-embed-text` | Unchanged. |

Measured on this AMD ~12 GB box, Ollama **0.32.14**: 9B soak 12/12 with zero
parser 500s, tool-choice 30/30, foundation 13/13, ~5.62 GiB at 16384. Qwen2.5
7B was faster to first token (warm TTFT ~165 ms) but lost soak fanout and
tool-choice. Gemma 4 12B passed soak but spent ~5 min thinking on a two-tool
turn — rejected as a daily driver.

The 14B dense niche is gone in Qwen3.5 (9B then 27B). A 27B offload was not
kept; 9B already beat 14B on the gates.

To revert this checkout: delete the `ollama` / `models` block at the top of
`data/config.local.yaml` and restart. Live 0.2.2 is untouched.

## What 0.2.2 (the installer) still uses

Until the next release, an **installed** 0.2.2 copy still has three chips:

| Role | Tag | Job |
|------|-----|-----|
| `fast` | `qwen2.5:7b` | Conversation, tools, texts |
| `research` | `qwen2.5:14b` | Deeper asks (8192 ctx) |
| `code` | `qwen2.5-coder:7b` | Edits / code |
| `vision` | `qwen2.5vl:3b` | See one local image |
| embed | `nomic-embed-text` | Recall / docs |

Those four chat/embed tags must stay on disk while 0.2.2 is installed.

Installer / first-run pull for **0.2.2**:

```powershell
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

This checkout, after the 9B pin:

```powershell
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
ollama pull qwen2.5vl:3b
```

A vision model is pulled the first time she looks at a picture if it is not
already local. Large screenshots are downscaled (long edge 1024 px) first.

STT and TTS stay on CPU. Idle wake is faster-whisper until
`models/wake/hey_arelis.onnx` exists; conversation and dictate are
Sherpa-ONNX Zipformer EN; TTS is Kokoro-82M `af_heart` (Piper Jenny
fallback). Sherpa mail homophones (`in box`, `emile`) are repaired in
`arelis/voice/stt.py` before skills see the transcript. Details:
[voice-wake.md](voice-wake.md).

Qwen3.5 streams native thinking one token per SSE frame. The thinking dock
joins those into one wrapping paragraph; that is UI, not a second model.

## How VRAM is shared

One chat model in graphics memory. `/role research` on this checkout does
**not** swap weights — it keeps 9B and changes the loop. After a research
turn she stays on that role for `router.rewarm_delay_s` (default 60) so
follow-ups do not pay a cold load, then pins `fast` again. Same tag, so that
pin is free.

Vision still unloads chat, runs one shot, then brings `fast` back.

Speech stays on the CPU.

## What “best” would mean, and why it is not here

| Ambition | Why not |
|----------|---------|
| Best answers in the world | Paid cloud or 70B+, not 12 GB at usable speed |
| Speculative decoding | Ollama + Windows + AMD does not expose it |
| 27B on this card | Offload. Gemma 12B already showed long think can beat “smarter” |
| Whisper `large-v3` | Steals the talk-feel on CPU |
| Thinking off on `fast` only | Possible (`think: false` on Ollama); not wired. 9B with thinking on is the daily try |

How the router, rooms, and vision unload fit the rest of the program:
[architecture.md](architecture.md).
