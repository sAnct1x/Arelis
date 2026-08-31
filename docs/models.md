# Models

Arelis thinks using models that live entirely on this machine, through
[Ollama](https://ollama.com/download). Nothing gets sent to a paid chat
API. Only one chat model is ever loaded and hot at a time.

Ollama itself is shared system-wide, so an installed copy and a source
checkout draw from the same set of tags. Just be careful not to
`ollama rm` a tag that another copy on the same PC still relies on.

## First open

The first time you launch a new copy, she looks at what your PC
actually has to offer — graphics memory, RAM, disk — and recommends
one chat model, along with an explanation of why. You can confirm it
or pick something else. Whatever you settle on ends up being used for
both Fast and Research modes.

The auto-pick is simply the largest Qwen 3.5 that comfortably fits
your hardware. Gemma and DeepSeek are both available in the list, but
neither is ever auto-picked. There's a reason for that: Gemma 4 12B
sat there thinking for several minutes on a simple two-tool turn, even
on a 12 GB card. DeepSeek is there if you want it, but it's opt-in
reasoning, not the default.

| This PC | Auto-pick |
|---|---|
| Modest laptop / ~6–7 GB or no dedicated card | `qwen3.5:4b` |
| ~8–16 GB | `qwen3.5:9b` |
| ~24 GB | `qwen3.5:27b` |
| ~32 GB+ | `qwen3.5:35b` |

If you don't have a dedicated graphics card, the recommendation sticks
to 4B or 9B even if your system RAM could technically hold a 27B
model — that combination would just crawl in practice.

If Ollama isn't already installed, setup downloads the official
Windows engine (about 1.4 GB) into `%LOCALAPPDATA%\Arelis-runtime`,
then pulls whichever tag you chose along with `nomic-embed-text`.
Tags land in Ollama's default store.

If a copy has already pinned `models.fast` in `config.local.yaml`, you
won't be asked again.

Every launch after that pins the chosen tag, then seeds Ollama's
prefix cache with the persona, the tool policy, and every tool schema
— roughly 5,500 tokens' worth. While that's happening, the window
just says **loading the model…** Once it's done, a warm hello takes
about a second. More detail in
[architecture.md](architecture.md).

## The shipped last-resort config (if setup hasn't run yet)

From `arelis/config/default.yaml`:

| Role | Tag | What it actually is |
|---|---|---|
| `fast` | `qwen3.5:9b` | Day-to-day driver. Thinking on. Can see images itself. File and git work always stays here. |
| `research` | `qwen3.5:9b` | Same weights, thinking on — just a deeper loop: more rounds, dual web hits, research tools. Same underlying model. |
| `vision` | `qwen2.5vl:3b` | Fallback only, for when the chat model in use can't see images itself. |
| embed | `nomic-embed-text` | Recall and document search. |

Measured on an AMD box with about 12 GB of memory, running Ollama
**0.32.14**: the 9B held up through soak testing at 12/12 with zero
parser 500s, tool-choice 30/30, and foundation 13/13. Qwen2.5 7B got
to first token faster, but it lost ground on soak fanout and
tool-choice. Gemma 4 12B passed the soak test too, but spent around
five minutes thinking on a two-tool turn — which is why it was
rejected as a daily driver, despite technically passing.

## The context window

`ollama.num_ctx` ships set to 65536, but setup actually overwrites
that per machine (details below) — so that shipped number is really a
last resort, not the intended value.

Qwen3.5 can technically accept a window as large as 262144, but we
don't pin it there, because that window gets paid for in graphics
memory whether or not a given conversation ever fills it. Here's what
resident memory actually looks like on the reference card, from
`scripts/measure_context_ceiling.py`:

| `num_ctx` | Resident |
|---|---|
| 16384 | 5.62 GiB |
| 32768 | 6.15 GiB |
| 65536 | 7.21 GiB |
| 131072 | 9.12 GiB |

All four settings stayed entirely on the GPU on a 12 GB card. 65536
was chosen specifically to leave breathing room for the desktop and
her browser. Roughly, that works out to about 34 KiB per token of
window, on top of roughly 5.1 GiB just for the model weights.

Setup actually derives the right window size from whatever card it
detects (`arelis/setup/context.py`) and writes it into
`config.local.yaml` — so a 24 GB card isn't stuck with a 12 GB-sized
answer, and an 8 GB card isn't handed a window it can't actually hold.
The floor is 32768, and that's not just being cautious: the persona,
telegraph policy, and skinny schemas already add up to about 5,500
tokens before you've even said anything, and history needs the rest.
Ollama discards overflow from the front of the context — which is
exactly where the persona lives — so this really matters.
`tests/test_prompt_fits_window.py` holds that math in place.

The old 14B dense-model niche is gone in Qwen3.5 — it jumps straight
from 9B to 27B. A 27B-with-offload setup wasn't kept, mainly because
9B already outperformed 14B on the test gates anyway.

You can select these manually in setup (they're never auto-picked):
Gemma 4 12B / 26B / 31B, or DeepSeek R1 8B / 14B / 32B / 70B.

Qwen3.5 can see images on its own, so a picture you send normally just
goes straight to whatever chat model is already loaded in memory.
`models.vision` only exists as a fallback, for a chat model that
reports it has no vision capability at all — it's only pulled if that
actually happens. Ollama gets asked directly what the current chat
model can do (via `/api/show`), so if you swap tags, that's handled
automatically without needing a config change. Large images are still
capped in size, though: 1024 px on the 3B fallback window, or 2048 px
when the chat model itself is doing the looking.

If you're working from source and don't want to wait on setup, you
can just pull these directly:

```powershell
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
```

## Voice

Speech-to-text and text-to-speech both stay on the CPU. Idle wake
detection uses faster-whisper until `models/wake/hey_arelis.onnx`
exists on disk. Actual conversation and dictation use Sherpa-ONNX
Zipformer EN. Text-to-speech is Kokoro-82M (the `af_heart` voice),
with Piper Jenny as a fallback. More in
[voice-wake.md](voice-wake.md).

Qwen3.5 streams its native thinking one token per SSE frame. The
thinking dock on screen just joins all of those into one wrapping
paragraph for you to read — housekeeping details sit below it rather
than cluttering the actual thought process. Worth noting that's purely
a UI choice, not a second model running underneath.

## How graphics memory gets shared

Only one chat model lives in graphics memory at a time. Switching to
`/role research` doesn't actually swap out weights when both roles
point at the same tag — it just changes the reasoning loop instead.
After a research-mode turn, she stays on that role for
`router.rewarm_delay_s` (60 seconds by default), so a quick follow-up
doesn't pay the cost of a cold reload, then pins back to Fast
afterward. Since it's the same underlying tag, that pin is essentially
free.

Looking at a picture no longer costs a model swap, either — since the
chat model can already see, the image just joins whatever turn it's
part of, and nothing gets unloaded. The only case where a swap still
happens is the fallback path: when the chat model genuinely has no
vision, chat gets unloaded, vision runs its one shot, and Fast gets
pinned back in afterward.

Speech, as mentioned, always stays on the CPU regardless.

## What 0.2.2 used

If you've got an installed 0.2.2 copy that hasn't been upgraded, it's
still running on three separate models:

| Role | Tag | Job |
|---|---|---|
| `fast` | `qwen2.5:7b` | Conversation, tools, texts |
| `research` | `qwen2.5:14b` | Deeper questions (8192 ctx) |
| `code` | `qwen2.5-coder:7b` | Edits and code |
| `vision` | `qwen2.5vl:3b` | Seeing a single local image |
| embed | `nomic-embed-text` | Recall and document search |

Those tags need to stay on disk as long as 0.2.2 is still installed
on the same PC.

## What "best" would actually mean, and why it isn't here

| Ambition | Why not |
|---|---|
| Best answers in the world | That means paid cloud or a 70B+ model — not something that runs at usable speed on 12 GB |
| Speculative decoding | Ollama + Windows + AMD doesn't expose this |
| 27B on a 12 GB card | Would require offloading. Gemma 12B already showed that "thinks longer" doesn't mean "smarter" |
| Whisper large-v3 | Would eat the responsiveness that makes voice feel natural, running on CPU |
| Thinking off, Fast mode only | Technically possible (`think: false` in Ollama) — just not wired up. 9B with thinking on is what's actually been tested and trusted day to day |

For how the router, rooms, and vision unloading tie into everything
else, see [architecture.md](architecture.md).
