# The 3D avatar

Arelis shows her as a full-body 3D figure drawn with three.js inside the app. The
scene runs from files that ship with Arelis. Nothing is loaded from the internet.

## Where the model file goes

The model is not part of the download. Put it here:

```
%LOCALAPPDATA%\Arelis\avatar\ellah.glb
```

Create the `avatar` folder if it is not there. Restart Arelis after adding the file.

To use a file somewhere else, set the `ARELIS_AVATAR_GLB` environment variable to its
full path before starting Arelis.

Her body movement comes from a second file, `ellah-anim.glb`, which holds recorded
motion clips. Put it in the same folder as the model:

```
%LOCALAPPDATA%\Arelis\avatar\ellah-anim.glb
```

To keep it somewhere else, set `ARELIS_AVATAR_CLIPS` to its full path. This file is
required: always copy it alongside `ellah.glb`. Without it she still appears, speaks
and blinks, but her body stands still in its neutral rest pose, and Arelis logs an
error naming the path it looked in.

## Where she stands

She is part of the window itself, not a panel you open or close.

- Night and Sodium: a band down the right side of the window, top to bottom. The chat
  ends where her band begins, so she never sits behind your messages.
- Night and Sodium with the Quick 3D figure (`ARELIS_AVATAR_ENGINE=qq3d`): she is the base layer
  of the whole window, as in Filament. She stands at the right, full height, head to
  toe, with no band or box around her. The chat keeps the space to her left, and her
  captions sit over her lower body.
- Filament: she is the base layer of the whole window. She always stands at the
  window's full height, head to toe, with her centre a little right of centre. There
  is no band, no box and no edge around her. The orbit ring, reality and any tiles
  you open sit in the space to her left, on top of her layer. Clicks on her go
  straight through to the room behind her. When the window spans two or three
  screens, she and the orbit stay on your home screen.

She is not a panel or dock in any room. There is no View menu entry for her and no
Ctrl+1, and the saved window layout no longer records her.

### The Filament load

When you enter Filament she comes up first. Once her scene is ready (or after six
seconds, or straight away if the 3D view cannot start), the orbit ring grows out of
her centre over about two seconds, easing in and out. The threads between her and
the ring stay attached the whole time.

A tile you open in Filament grows out of the end of its own filament: it starts as a
small seed where its thread meets the plate, then opens to full size.

She stays in view when the app goes idle. She is always framed head to toe and the
view refits when the window changes size.

## What she does

- Her body moves with recorded motion: resting, breathing, shifting her weight, talking
  with her hands, nodding while she listens or thinks. Each state blends into the next
  over a moment instead of snapping to a fixed pose.
- While she speaks, her mouth and jaw follow the voice.
- When the microphone is listening, she shows it.
- She blinks, shifts her weight and gestures on her own.

## Stopping her

Press the stop button, or say "stop". Clicking her does nothing: clicks pass through
her to whatever is behind.

## While she loads, or if she cannot start

While the scene loads you see a soft, still glow in the room's colour where she will
stand. There is no face in it. She appears in its place once the scene is ready.

The glow stays, and she does not appear, when the 3D view cannot run:

- no model file at the path above,
- the 3D engine (QtWebEngine) is not available,
- the graphics card or driver cannot run WebGL,
- the scene reports an error while loading or running,
- GPU space is on (`ARELIS_SOLAR_GL=1`), which cannot share the process with it.

To turn the 3D view off on purpose, set `ARELIS_WEB_AVATAR=0`.

## Choosing the Quick 3D figure

Set `ARELIS_AVATAR_ENGINE=qq3d`, or start with `--avatar-engine qq3d` (the flag wins).
On Windows a user variable you set after signing in is read from your saved settings
too, so a desktop icon picks it up without signing out first. The first avatar line in
the log names the choice, for example
`[avatar] engine=qq3d source=user-env room=filament`. The source is `flag`, `env`,
`user-env` or `default`. When Quick 3D cannot draw her, the same line ends with
`unavailable='...'` and the reason.

### Where the Quick 3D model comes from

The app reads her model from its own data folder, `avatar\qq3d` (the repo folder on
the dev copy, `%LOCALAPPDATA%\Arelis` once installed). `ARELIS_AVATAR_QQ3D_DIR`,
read from the process or from your saved Windows user variables, is only a fallback
for when that folder has no model. When the fallback is used, the app draws from it
right away and copies it into `avatar\qq3d` in the background, so the next start
reads its own copy. The startup line says which: `model=app`, `model=override` or
`model=none`, followed by the folder.

The app cannot build the model from `ellah.glb` by itself. The port
(`tools/avatar_q3d_export.py`, then `persona_q3d/convert.py` and `persona_q3d/port.py`)
needs headless Chrome with playwright, balsam and `ellah-anim.glb`, which a normal PC
does not have. Build it on a dev machine, then either copy the folder into
`avatar\qq3d` or point `ARELIS_AVATAR_QQ3D_DIR` at it once.

## Reading the log

Every avatar event is one line in the app log starting with `[avatar]`, so you can
find them all with a single search. The page's own console messages are included.

| Line | Means |
|---|---|
| `[avatar] unavailable reason=...` | The 3D view will not start, and why. |
| `[avatar] glb load path=... bytes=...` | The model file is being opened. |
| `[avatar] renderer init webgl2=... ratio=... size=WxH` | The drawing surface started. |
| `[avatar] clip loaded name=...` | A motion clip arrived (gesture track, walk). |
| `[avatar] clips load path=... bytes=...` | The motion file is being opened. |
| `[avatar] clips missing at <path>` | Error: the motion file is not there. Her body holds the rest pose. |
| `[avatar] mixer clips=...` | The motion clips loaded, with how many. |
| `[avatar] glb loaded ms=...` | The model finished loading, with the time it took. |
| `[avatar] scene ready ms=...` | She is built and drawing. |
| `[avatar] ready` | The app saw her ready and swapped out the glow. |
| `[avatar] clip play name=...` | She took a pose (`thinking`, `speaking`, `done`, `listening`, `idle`; one line per change, so a turn reads thinking, speaking, done, idle), or a gesture segment or walk phase began. |
| `[avatar] shader note unroll` | The D3D shader compiler unrolled a one-pass loop. Informational, not a fault. |
| `[avatar] lipsync start` / `stop` | Speech began or ended. |
| `[avatar] stop source=...` | Speech was stopped: `button`, `voice`, or another cause. |
| `[avatar] theme name=... tint=...` | The room changed and she was retinted. |
| `[avatar] resize region=X,Y,WxH` | Her place in the window changed: her band in Night and Sodium, the whole stage in Filament and in any room with the Quick 3D figure. |
| `[avatar] canvas resize size=WxH` | The scene followed that change. |
| `[avatar] filament load step=she appears` | Filament opened; the ring waits for her. |
| `[avatar] filament load step=ring grows origin=X,Y` | The ring starts growing out of her hub at X,Y. |
| `[avatar] filament load step=ring settled` | The ring is at full size. |
| `[avatar] tile spawn name=... origin=X,Y` | A Filament tile started growing from its filament at X,Y. |
| `[avatar] webgl lost` / `restored` | The graphics context dropped or came back. |
| `[avatar] failed reason=...` | The scene gave up; the glow stays. |
| `[avatar] js ...` | Any other console message from the page, with file and line. |

## Blank-frame A/B switches (diagnostics)

These only matter when chasing blank frames, where she renders but some frames never reach
the screen. Each is read once at start and shows in the `graphics chromium_flags=... arm=...
qt_rhi=...` line of the startup surface report. Leaving them unset keeps normal behaviour.

| Variable | Value | What it changes |
|---|---|---|
| `ARELIS_QT_RHI` | `opengl` | Qt shows her frames through OpenGL instead of Direct3D 11 (sets `QSG_RHI_BACKEND` and `QT_WIDGETS_RHI_BACKEND`). |
| `ARELIS_GPU_ARM` | `novsync` | Direct3D 11 as usual, plus `--disable-gpu-vsync --disable-frame-rate-limit`. Logs as `arm=d3d11+novsync`. |
| `ARELIS_GPU_ARM` | `none`, `d3d11`, `gl`, `nocomp` | Earlier arms, already measured on Atria. |
| `ARELIS_AVATAR_BACKDROP` | `opaque` | Paints the room colour under her instead of a see-through page. |
| `ARELIS_PRESERVE_BUFFER` | `off` | Her canvas without preserveDrawingBuffer. |
