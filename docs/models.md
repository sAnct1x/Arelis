# Models — honest fit for this machine

Hardware this page assumes: **AMD RX 6700 XT 12 GB**, **64 GB RAM**, **Ollama on
Windows**, local-first / **no paid APIs**.

## Short answer

**No — this is not “the best the world has.”** Frontier cloud models (GPT-class,
Claude-class, Gemini-class) still beat any 7B–14B local model on hard reasoning,
long agents, and messy tool use.

**Yes — within free + fully-on-GPU on a 12 GB card, your stack is in the right
band.** Qwen2.5 7B / 14B / Coder 7B is still a mainstream 2026 local recommendation
for this VRAM tier. You are not on a random weak pick.

Novelty for Arelis is **orchestration + tools + memory under latency**, not
winning LMSYS with a bigger weight file.

## What you run today

| Role | Tag | Job | Fit |
|------|-----|-----|-----|
| `fast` | `qwen2.5:7b` | Conversation, tools, SMS | ~4.8 GiB, ~49 tok/s warm — right default |
| `research` | `qwen2.5:14b` | Deeper asks | ~9.6 GiB, ~29 tok/s — quality ceiling that still fits |
| `code` | `qwen2.5-coder:7b` | Edits / code | Same size class as fast; swap when coding |
| `vision` | `qwen2.5vl:3b` | See one local image (tool) | Fits 12 GB only when chat is unloaded; never co-resident with 14B |
| embed | `nomic-embed-text` | Recall / docs | Tiny; load briefly |
| STT | Sherpa-ONNX Zipformer EN (CPU); faster-whisper `base` fallback | Speech in (dictate / conversation) | Streaming-capable pack; GPU reserved for chat |
| TTS | Kokoro-82M `af_heart` (CPU ONNX); Piper Jenny fallback | Speech out | Local, barge-in friendly; GPU stays on chat |

Operator pull (not required for pytest): `ollama pull qwen2.5vl:3b`.
The `vision` tool unloads chat, runs one VL shot, then rewarms fast — see
[architecture.md](architecture.md).

Measured on this box: `logs/utilization_bench.json`, `docs/foundation.md`.

## What “best” would mean (and why we do not)

| Ambition | Reality on this box |
|----------|---------------------|
| Best answers in the world | Needs paid cloud or 70B+ (does not fit 12 GB at speed) |
| Speculative decoding 2× tok/s | Ollama GGUF path on Windows does **not** expose it; MTP is mostly Mac/MLX or llama.cpp+ROCm rabbit holes (and your card is RDNA2, not the RDNA4 recipes people publish) |
| 32B / Qwen3.6 27B full GPU | Offload → often *slower* than 14B on-GPU |
| Whisper `large-v3` | Better transcripts, much slower on CPU; steals the “snappy talk” feel |
| Best embed in existence | Larger multilings (e.g. bge-m3) help some RAG; nomic remains the simple local default |

## Optional upgrades (still free — try after live smoke)

Do **not** change defaults until tomorrow’s live test is green. Then A/B with
`scripts/bench_foundation.py --live` and `scripts/bench_utilization.py`.

| Slot | Candidate | Why consider | Risk |
|------|-----------|--------------|------|
| fast | `qwen3.5:9b` | Mid-2026 chatter: strong sub-10B tool-calling on 12 GB | Tag may not exist on your Ollama yet; only keep if foundation eval ≥ 7B **and** TTFT not worse |
| research | `qwen3:14b` (Q4) | Newer Qwen3 family; possibly better agents | Tool-calling + TTFT may regress; measure |
| code | `qwen2.5-coder:14b` | Stronger code than 7B coder | Same VRAM class as research; cold when swapping |
| fast | `qwen3:8b` | Newer small generalist | Only if tool eval ≥ current 7B **and** TTFT not worse |
| STT | whisper `small` | Fewer name errors | +latency on every utterance |

Pull example (when you choose to trial):

```text
ollama pull qwen3:14b
```

Then temporarily set `models.research: "qwen3:14b"` and re-run the live
foundation matrix before keeping it.

## Research-speed on *this* stack (what we actually ship)

1. **Delayed re-warm** (`router.rewarm_delay_s`, default 45 s) — back-to-back
   research turns keep 14B warm; then VRAM returns to `fast`.
2. **Non-default `keep_alive: 5m`** — research/code are not evicted the instant
   a turn ends.
3. Speculative decoding — **deferred** until a runner you accept supports it
   without wrecking AMD/Windows simplicity.

## Bottom line

- **Best absolute quality?** No — cloud wins.
- **Best free local 12 GB assistant stack?** You are on the recommended ridge
  (Qwen2.5 7B chat + 14B research + coder). Tune with measurement, not hype.
