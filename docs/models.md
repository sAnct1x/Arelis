# Models

Arelis thinks using models that live entirely on this machine, through
llama.cpp (llama-server). Nothing gets sent to a paid chat API. Only one
chat model is ever loaded and hot at a time.

## First open

The first time you launch a new copy, she asks which folder she can use,
then downloads a chat model. See [first-run.md](first-run.md).

Fast and Research use the same shipped name unless you pin another one in
`config.local.yaml`.

If a copy has already pinned `models.fast` in `config.local.yaml`, that
name is what chat sends.

Every launch after that pins the chat model, then seeds the prefix cache
with the persona, the tool policy, and every tool schema: roughly 5,500
tokens. While that is happening, the window just says **loading the model…**
Once it is done, a warm hello takes about a second. More detail in
[architecture.md](architecture.md).

## The shipped config

From `arelis/config/default.yaml`:

| Role | Name | What it actually is |
|---|---|---|
| `fast` | `Qwen3.6-35B-A3B` | Day-to-day name sent to llama-server. File and git work stays here. |
| `research` | `Qwen3.6-35B-A3B` | Same name. A deeper loop: more rounds, research tools. |
| `vision` | `Qwen3.6-35B-A3B` | Same weights. The 35B reads pictures itself. |
| embed | `nomic-embed-text` | Recall and document search, on the CPU embed server. |

Chat is Qwen3.6 35B-A3B on llama.cpp. The recommended file is 22.1 GB.
A machine with less memory uses the smaller file, 16.6 GB.

## The context window

`llamacpp.default_cap` ships at 32768. The history budget is the smaller of
that cap and the `n_ctx` llama-server reports.

The window is paid for in graphics memory whether or not a conversation
fills it. The 35B on a 12 GB card uses 32768.

The persona, the tool policy, and the skinny schemas already add up to
about 5,500 tokens before you have said anything, and history needs the
rest. Overflow drops from the front of the context, which is where the
persona lives. `tests/test_prompt_fits_window.py` holds that math in place.

## Pictures on the 35B

When chat uses llama.cpp, the model is Qwen 3.6 35B. A picture you send
is read by that same model. Attach a picture in chat and ask about it:
the pixels go in that same request as your words. The server loads a Q8
picture file next to the weights, keeps flash attention off, and caps
each picture at 1024 image tokens. If the 35B was already running,
restart it once so it loads that file.

## Voice

Speech-to-text and text-to-speech both stay on the CPU. Those
weights are fetched on first open, not stuffed in the setup `.exe`;
the idle line says **getting the ear…** until wake can hear. Idle
wake uses faster-whisper until `models/wake/hey_arelis.onnx` exists.
Conversation and dictation use Sherpa-ONNX Zipformer EN. Speech out
is Kokoro-82M (`af_heart`), Piper Jenny as fallback. More in
[voice-wake.md](voice-wake.md).

Qwen3.5 streams its native thinking one token per SSE frame. The
thinking dock on screen just joins all of those into one wrapping
paragraph for you to read. Housekeeping details sit below it rather
than cluttering the actual thought process. A vision look uses that
same stream, so the dock is not blank while she reads a page. Worth
noting that's purely a UI choice, not a second model running
underneath.

## How graphics memory gets shared

Only one chat model lives in graphics memory at a time. Switching to
`/role research` doesn't actually swap out weights when both roles
point at the same tag. It just changes the reasoning loop instead.
After a research-mode turn, she stays on that role for
`router.rewarm_delay_s` (60 seconds by default), so a quick follow-up
doesn't pay the cost of a cold reload, then pins back to Fast
afterward. Since it's the same underlying tag, that pin is essentially
free.

Looking at a picture no longer costs a model swap, either. Since the
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
| Best answers in the world | That means paid cloud or a 70B+ model, not something that runs at usable speed on 12 GB |
| Speculative decoding | Not used on this Windows AMD card |
| 27B on a 12 GB card | Would require offloading. Gemma 12B already showed that "thinks longer" doesn't mean "smarter" |
| Whisper large-v3 | Would eat the responsiveness that makes voice feel natural, running on CPU |
| Thinking off, Fast mode only | Possible, just not wired up. 9B with thinking on is what has been tested day to day |

For how the router and vision unloading tie into everything
else, see [architecture.md](architecture.md).

## Native tool calling

Tool choice is the model's, from the tool descriptions it was given, which tools
are loaded, and what a tool result already showed. There is no regex layer that
picks a tool from the wording of the ask.

`agent.native_tool_calling` (default `false`) only adds a few parameter hints
and a nudge when the user named a tool that has not run yet. It does not choose
the tool. Confirm cards, send locks, and the honesty floor stay on either way.

To try the hints, add to `data/config.local.yaml`:
```yaml
agent:
  native_tool_calling: true
```
