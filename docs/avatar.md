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
- Filament: she is the hub at the bottom left. There is no tile for her. The threads
  run from her to the orbit ring, and the strand to each open tile starts at her. The
  chat keeps its full width here, since she is not in a side band.

She is not a panel or dock in any room. There is no View menu entry for her and no
Ctrl+1, and the saved window layout no longer records her.

### The Filament load

When you enter Filament she comes up first. Once her scene is ready (or after six
seconds, or straight away if the 3D view cannot start), the orbit ring grows out of
her hub point over about two seconds, easing in and out. The threads between her and
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
| `[avatar] resize mode=... region=X,Y,WxH` | Her place in the window changed. `mode=band` in Night and Sodium, `mode=hub` in Filament. |
| `[avatar] canvas resize size=WxH` | The scene followed that change. |
| `[avatar] filament load step=she appears` | Filament opened; the ring waits for her. |
| `[avatar] filament load step=ring grows origin=X,Y` | The ring starts growing out of her hub at X,Y. |
| `[avatar] filament load step=ring settled` | The ring is at full size. |
| `[avatar] tile spawn name=... origin=X,Y` | A Filament tile started growing from its filament at X,Y. |
| `[avatar] webgl lost` / `restored` | The graphics context dropped or came back. |
| `[avatar] failed reason=...` | The scene gave up; the glow stays. |
| `[avatar] js ...` | Any other console message from the page, with file and line. |
