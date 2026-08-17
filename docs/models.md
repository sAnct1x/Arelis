# Models

Arelis thinks with models that run on your own machine, through
[Ollama](https://ollama.com/download). Nothing is sent to a paid API. The
defaults below are what a **12 GB graphics card** can hold at once — one chat
model at a time, which is the whole point of the role switcher.

They are not the best models in the world. Frontier cloud models still beat any
7B–14B local model on hard reasoning, long agents, and messy tool use. Within
free and fully on the GPU at this size, Qwen2.5 7B / 14B / Coder 7B is a
mainstream local choice, not a random weak pick. What is unusual about Arelis
is the orchestration, the tools and the memory sitting under that, not a bigger
weight file.

## What she uses

| Role | Tag | Job | Fit on 12 GB |
|------|-----|-----|----------------|
| `fast` | `qwen2.5:7b` | Conversation, tools, texts | ~4.8 GiB, ~49 tok/s warm — the default |
| `research` | `qwen2.5:14b` | Deeper asks | ~9.6 GiB, ~29 tok/s — the quality ceiling that still fits |
| `code` | `qwen2.5-coder:7b` | Edits / code | Same size class as fast; swap when coding |
| `vision` | `qwen2.5vl:3b` | See one local image | Fits only when chat is unloaded; never next to 14B |
| embed | `nomic-embed-text` | Recall / docs | Tiny; loaded briefly |
| STT | Sherpa-ONNX Zipformer EN (CPU); faster-whisper `base` fallback | Speech in | GPU stays on chat |
| TTS | Kokoro-82M `af_heart` (CPU ONNX); Piper Jenny fallback | Speech out | Local, barge-in friendly |

Pull the three chat models and the embed model up front (several gigabytes,
once):

```powershell
ollama pull qwen2.5:7b
ollama pull qwen2.5:14b
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

If the card is smaller than 12 GB, skip the 14B pull. She will still converse
on `fast`. The vision model is pulled the first time she looks at a picture
(`ollama pull qwen2.5vl:3b` if you want it early). Looking at a picture
unloads chat, runs one shot, then brings `fast` back. Large screenshots are
downscaled (long edge 1024 px) before they are sent, because a 1440p capture
does not fit in the vision model's context otherwise.

The tags live in `arelis/config/default.yaml` under `models:` and
`memory.embed_model`. Changing them is a config edit, not a rebuild.

## How VRAM is shared

Only **one** chat model is meant to be in graphics memory. `/role research`
unloads 7B and loads 14B; a few seconds of silence is the swap, not a hang.
After a research or code turn she keeps that heavier model warm for a minute
(`router.rewarm_delay_s`, default 60) so a follow-up does not pay the cold
load, then pins `fast` again. Research and code also use a non-default
`keep_alive: 5m` so Ollama does not evict them the instant a turn ends.

Speech recognition and speech stay on the CPU, so talking does not kick the
chat model off the card.

## What “best” would mean, and why it is not the default

| Ambition | Why it is not shipped |
|----------|------------------------|
| Best answers in the world | Needs a paid cloud API or 70B+, which does not fit 12 GB at speed |
| Speculative decoding for 2× tok/s | Ollama's Windows path does not expose it |
| 32B / a 27B full GPU | Offload is often *slower* than 14B sitting on the card |
| Whisper `large-v3` | Better transcripts, much slower on CPU; steals the “snappy talk” feel |
| A larger embed model | Helps some recall; nomic remains the simple local default |

## Optional experiments

These are not better by default. Try one at a time, and keep it only if it is
at least as good at tool-calling and not slower to first token than what you
have.

| Slot | Candidate | Why consider | Risk |
|------|-----------|--------------|------|
| fast | `qwen3.5:9b` | Stronger sub-10B tool-calling on 12 GB, when the tag exists | Tag may not be on your Ollama yet |
| research | `qwen3:14b` (Q4) | Newer Qwen3 family | Tool-calling and first-token time may regress |
| code | `qwen2.5-coder:14b` | Stronger code than 7B coder | Same VRAM class as research; cold when swapping |
| fast | `qwen3:8b` | Newer small generalist | Same measurement bar as the 9B |
| STT | whisper `small` | Fewer name errors | Extra latency on every utterance |

```text
ollama pull qwen3:14b
```

Then temporarily set `models.research: "qwen3:14b"` in
`data/config.local.yaml` before keeping it.

How the router, the role chips and the vision unload fit the rest of the
program: [architecture.md](architecture.md).
