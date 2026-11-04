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

## The Quick 3D model

Her built Quick 3D model is part of Arelis. It is committed in `arelis/assets/qq3d`
(`Ellah_aether.qml` plus its meshes, maps, clips, shaders and geometry) and ships in the
package, so a checkout and every installer have it with no download and no build flag.
`ellah.glb` and renders are never committed.

Where Arelis reads it from is described once, under
[Where the Quick 3D model comes from](#where-the-quick-3d-model-comes-from).

The Windows installer puts the model in your data folder, not the program folder:

```
%LOCALAPPDATA%\Arelis\avatar\qq3d\Ellah_aether.qml
```

A plain uninstall keeps that folder; choosing to delete all Arelis data removes it. If you
moved your data with `ARELIS_DATA_DIR`, copy the `qq3d` folder into that data folder's
`avatar` folder yourself, because the installer always writes to `%LOCALAPPDATA%\Arelis`.

To rebuild it after the look changes, run `tools/avatar_q3d_export.py` (writes the scene),
then `python -m arelis.ui.persona_q3d.convert --out DIR` (balsam on `ellah-anim.glb`), then
`python -m arelis.ui.persona_q3d.port --converted DIR`, and copy `DIR` over
`arelis/assets/qq3d`. Check that no `.glb` landed in it and that no file is over 50 MB
(GitHub refuses files over 100 MB).

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
- With the Quick 3D figure, in every room, her head rests turned a little toward the
  chat and tiles on the left of the screen, not away from them.

She is not a panel or dock in any room. There is no View menu entry for her and no
Ctrl+1, and the saved window layout no longer records her.

### The Filament load

When you enter Filament she comes up first. Once her scene is ready (or after six
seconds, or straight away if the 3D view cannot start), the orbit ring grows out of
her centre over about two seconds, easing in and out. The threads between her and
the ring stay attached the whole time.
The tile names do not travel with it: once the ring settles, each name fades in at its
own spot over about three quarters of a second, together with the ring of light around
its node.
The beads, the pulses of light and the reality orb appear at that same moment, on the
same fade as the names, never while the ring is still growing.

A tile you open in Filament grows out of its own node on the tree, then opens to full
size. It reopens at the size and spot you left it, even outside the main window.

The tree's base spreads three ways on the floor: right, toward you and away from you,
besides the long roots to the left, and the right side now carries about as much weight as
the left. Every root and buttress fades in from its far end and
runs on into the trunk, so no strand stops short. The floor light starts just outside her
near foot (`OrbitState` `feet`, 0.14 of the height off her hub, toward the tree) as a wide
soft swell, not a hot point between her feet. In Filament she stands at `FIGURE_SCALE` (0.85, `persona_stage.py`) of her full height,
soles on the floor line: the camera backs off by 1 / 0.85, and her hub and the floor link's
start derive from the same constant. The tree keeps drawing under the open chat. The strands that leave the trunk's foot fade in
slowly, so none sweeps off to the right and stops in the air.
Its fibers are drawn in four quarters into textures, one quarter redrawing per frame in
turn, and laid together into one cached texture, so a frame composites one fiber texture,
not four. The tree keeps moving under the chat too.

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

Arelis looks for her model in this order and uses the first folder that holds
`Ellah_aether.qml` (or `Ellah_anim.qml`):

1. `avatar\qq3d` in the app's data folder (the repo folder on the dev copy,
   `%LOCALAPPDATA%\Arelis` once installed, where the installer puts it).
2. `ARELIS_AVATAR_QQ3D_DIR`, read from the process or from your saved Windows user
   variables. When this one is used, the app draws from it right away and copies it into
   `avatar\qq3d` in the background, so the next start reads its own copy.
3. The bundled `arelis/assets/qq3d`. It is never copied.

The startup line says which: `model=app`, `model=override` or `model=bundled`, followed
by the folder.

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
| `[avatar] lipsync start` / `stop` | Speech began or ended. A typed reply counts too: while its text streams in, each chunk keeps a calm syllable envelope (about 4 a second) on her mouth until about half a second after the last chunk; voice audio takes over whenever it plays. |
| `[avatar] stop source=...` | Speech was stopped: `button`, `voice`, or another cause. |
| `[avatar] theme name=... tint=...` | The room changed and she was retinted. |
| `[avatar] resize region=X,Y,WxH` | Her place in the window changed: her band in Night and Sodium, the whole stage in Filament and in any room with the Quick 3D figure. |
| `[avatar] canvas resize size=WxH` | The scene followed that change. |
| `[avatar] filament load step=she appears` | Filament opened; the ring waits for her. |
| `[avatar] filament load step=ring grows origin=X,Y` | The ring starts growing out of her hub at X,Y. |
| `[avatar] filament load step=ring settled` | The ring is at full size. |
| `[avatar] tile spawn name=... origin=X,Y` | A Filament tile started growing from its node on the tree at X,Y. |
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

## One Quick surface (`ARELIS_SURFACE`, default quick, slice 1)

`ARELIS_SURFACE=quick` (process env, else the saved Windows user variable) makes the window's
bottom layer a single full-window `QQuickWidget` (`arelis/ui/persona_face/quick_surface.py`,
`qq3d/QuickSurface.qml`). It paints the void, shows the Filament orbit frame as an `Image`
layer, and hosts her `Avatar.qml` at her panel's rect through `QuickSurfaceAvatar`, which has
the same API as `QQ3DAvatar`. Nothing is read back from the GPU, and the window's
`paintEvent` stops blitting the orbit. The Quick surface (her tree orbit) is now the default:
unset means quick. Set `ARELIS_SURFACE=widget` (any value other than `quick`) to get the old
orbit back (the `QQuickRenderControl` readback and the paintEvent blit). Startup logs
`[avatar] surface=quick|widget source=...`.

Why `QQuickWidget` and not `createWindowContainer`: a container is a native child window, and
on Windows it always draws above its sibling widgets, so tiles and chrome couldn't sit on top
of it. `QQuickWidget` is composited in widget z-order, so `lower()` puts it under everything.
The orbit is still painted in Python (`filament_render.py`) in this slice and uploaded as an
image. Slice 2 moves it into QML and shaders.

### Slice 2: the orbit on the GPU

Under the flag `qq3d/QuickOrbit.qml` draws the ring (with its `ring_grow` intro out of her
hub), the four additive strands, the 1100 dust grains and the three hub threads as
`ShaderEffect`s over the void, with no Python per frame. The stages are GLSL in
`qq3d/orbit/` (each is `common.glsl`, the same path arithmetic as `FilamentField._point_fn`,
plus its body) baked to `.qsb` by `python tools/build_orbit_shaders.py`; the `.qsb` files are
committed and ship with the package. Re-run the script after editing a stage.

State flows through one `OrbitState` QObject (`persona_face/orbit_state.py`), set as the
`orbitState` context property: the settled ring, hub, ribbon halves, fade margin, span,
weather targets, ring phase and colours. The atmosphere tick calls `update()`, and each
property emits only when it changes. QML eases the weather and runs the clock on a
`FrameAnimation`. Python sends a `sync` of the sim clock once a second so the beads stay on
the path. The `FieldRenderer` worker paints only what is not ported yet (beads with the
reality orbit, stems, tethers; slice 3) onto a clear image, which the surface adds over the
GPU layers. Chips are still widgets. `[filament] orbit fps=N` comes from QML's frame counter
every 5 s (`OrbitState.reportFps`).

The Quick 3D mixer stands her upright by turning Waist, Spine01 and Spine02 back about a
third of the 6.5 deg each, so her stomach no longer folds at the waist.

- Arelis rests facing you or a touch toward the chat side, in every theme and state. She still sways and looks around, but no animation leaves her turned away.
- Switching themes while she is still loading no longer leaves the breathing loading glow running.
- Her lips keep moving with a reply after the window is minimized and restored mid-reply.
