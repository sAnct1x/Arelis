# Images

Arelis makes and changes pictures on this computer. Nothing is sent to a
cloud image service.

## Making a new picture

The `image` tool draws a new picture from a prompt. The default engine is
a built-in copy of stable-diffusion.cpp (Vulkan) and one model, FLUX.2
klein 4B. On a typical 12 GB AMD card, one 1024 pixel picture takes about
two minutes after chat has been paused.

The first time you ask for a picture, Arelis downloads about 5 GB of
model files (Apache-2.0) and a small Windows program (MIT). Files over
50 MB need an Allow card, even if pictures are set not to ask first in
Settings. The card shows the download size and Allow and Deny in every
theme, including filament. If a download fails or you stop it, unfinished
files are deleted.

While a picture is being made, chat is paused so the image model can use
the graphics card. Chat shows that in plain words: chat is paused while
the picture is made, usually a couple of minutes, then about a minute to
bring chat back. When the picture is done, chat shows that it is being
brought back and starts llama-server again right away, without freezing
the rest of the app. While chat is coming back, Arelis feeds the current
conversation to the chat model again so the next message is not a long
cold wait. If chat cannot come back after the picture, a plain message
says so and asks you to try closing Arelis and opening it again.
If the picture program fails, is stopped, or Arelis quits, chat
is also started again. If Arelis is closed or killed while a picture is
being made, the next time you open Arelis it starts the chat model again
if it was left stopped. A message typed while a picture is in progress
waits, then is answered after chat is back.

In a narrow chat window (around 380 pixels wide), the message box shrinks
and wraps so the text does not cover the clear or attach buttons.

You can ask for one to four variations, reuse a seed, pick a size or
aspect, or fold in a style. Each picture is saved under `outputs/images/`
with a small sidecar file that records the prompt and seed.

There is no added content filter on this backend. NSFW pictures and real
faces are allowed. This is local, and it is your call.

## Editing a picture

Restyle, inpaint and outpaint are not ready yet on the built-in engine.
If you already run ComfyUI, you can choose that backend in Settings and
those edits still go there. Exact crop, resize, rotate, pad, warmth and
text overlay stay on `image_edit` (Pillow), which does not need the GPU.

## Settings

Settings, then Pictures, chooses the engine:

- Built-in (FLUX.2 klein 4B, local), the default.
- ComfyUI, if you already have it. This is optional and is not removed.

Model files can also live in a folder you set (`tools.image.sdcpp.model_dir`
and `bin_dir` in config). The default is still the local folder Arelis
manages.

## How this is different from before

Pictures used to need a separate ComfyUI install and an older Stable
Diffusion 1.5 or SDXL checkpoint, and they often failed on a fresh PC.
The 35B chat model also stayed in video memory, so the image job fought
it for the card. The built-in engine and the GPU lease are the fix for
those two problems.

## What is not in this pass

Instruction edits ("make her jacket red"), a brush mask, and other
models (including a high quality editor) come later. ControlNet is out
of scope. The built-in Windows Vulkan program is what this pass ships;
other operating systems can still use ComfyUI if it is already set up.
