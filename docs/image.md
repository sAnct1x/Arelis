# Images

Arelis makes and changes pictures in two tools. `image` invents or
restyles pixels through a local ComfyUI server. `image_edit` does
arithmetic on a file that already exists (Pillow). Vision looks.
None of this is a cloud API.

## Scorecard (baseline 2026-09-05)

10/10 means this product, not Midjourney. Weights are not bundled.

| Category | Now | 10/10 |
|---|---|---|
| Ship | 10 | Discover Comfy on disk; start it when found; one-step fail if missing |
| Txt2img | 10 | SDXL when present; aspect; style; 1–4 variations; seed; sidecar |
| Restyle | 10 | img2img with path + denoise + style |
| Surgical | 10 | Region inpaint, outpaint, optional rembg |
| Pixel | 10 | Crop box/half, 2× enlarge, pad, warmth, plus rotate/grade/overlay |
| Loop | 10 | Variations, seed again, upscale, timeout is a failure |
| Desk | 10 | Gallery of recent outputs; sidecar tooltip |
| Intuitiveness | 10 | Caption, human fail, empty-desk line, errand, Allow sentence |
| Usability | 10 | Click / arrows, prompt tooltip, live shimmer, open on the picture |
| Visual | 10 | Well / strip / thumb chrome, square selected thumb, Plex overlay |
| Scalability | 10 | 16-thumb cap, n≤4, decode at display size |
| Maintainability | 10 | Rail, copy, and rubric modules; one object name per role |
| Routing | 10 | Every verb lands on one tool; never SMS |
| Ops | 10 | Discover, sidecar, hard fail, VRAM park |
| Safety | 10 | Local only, sandbox, Allow, strong default negatives |

## What each 10 looks like

- **Ship.** Common portable / Documents / Desktop Comfy roots are
  found without a recursive drive scan. `launch_cwd` empty still
  starts that copy. If nothing is there, the fail names
  `tools.image.launch_cwd` and `auto_start` once.
- **Txt2img / restyle.** One call. Optional `n` (1–4), `aspect`,
  `style`, `path` + `denoise`. A `.json` sidecar sits next to the PNG.
- **Surgical.** `mask_region` (left / right / top / bottom / center)
  or a pixel box inpaints. `outpaint` grows the canvas. `remove_background`
  uses rembg when installed.
- **Pixel.** Exact crop, 2× enlarge, pad, warmth. Original never overwritten.
- **Loop / ops.** A timeout is `[fail:image]`, not a queued success.
  Comfy parks after idle so chat gets the card back.
- **Desk.** Workspace image mode lists recent `outputs/images/` thumbs.
  The open picture is the selected square. Caption and tooltip carry
  the sidecar prompt. Left / right walk the rail. Open stays on that face.
- **Feel.** `arelis/tools/image_polish.py` is the rubric (intuitiveness,
  usability, visual, scalability, maintainability). A 10 is every named
  check on that axis. Overlay type is IBM Plex with a sodium stroke.
- **Routing.** “Four versions” → `image n=4`. “Upscale this” →
  `image_edit scale=2`. “Remove the background” → `image`.
  “Crop the left half” → `image_edit`. “Make this a watercolor” →
  `image` + path. “Outpaint / uncrop” → `image outpaint=all`.
  “Change the left of the picture” → `image mask_region=left`.
  “Do that again” / same seed → `image` with the last sidecar seed and prompt.

## Out of scope

Bundling a multi-gigabyte checkpoint. ControlNet. A painted mask
studio. Midjourney-grade prompt rewrite. Cloud generate unless a key
is already in config.
