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

## Where she stands

She is part of the window itself, not a panel you open or close.

- Night and Sodium: a band down the right side of the window, top to bottom. The chat
  ends where her band begins, so she never sits behind your messages.
- Filament: she still lives in her tile for now. The hub at the bottom left, where the
  threads start, comes in a later update.

She stays in view when the app goes idle. She is always framed head to toe and the
view refits when the window changes size.

## What she does

- Thinking, speaking and done each have their own pose.
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
| `[avatar] glb loaded ms=...` | The model finished loading, with the time it took. |
| `[avatar] scene ready ms=...` | She is built and drawing. |
| `[avatar] ready` | The app saw her ready and swapped out the glow. |
| `[avatar] clip play name=...` | A gesture segment or a walk phase began. |
| `[avatar] lipsync start` / `stop` | Speech began or ended. |
| `[avatar] stop source=...` | Speech was stopped: `button`, `voice`, or another cause. |
| `[avatar] theme name=... tint=...` | The room changed and she was retinted. |
| `[avatar] resize mode=... region=X,Y,WxH` | Her place in the window changed. |
| `[avatar] canvas resize size=WxH` | The scene followed that change. |
| `[avatar] webgl lost` / `restored` | The graphics context dropped or came back. |
| `[avatar] failed reason=...` | The scene gave up; the glow stays. |
| `[avatar] js ...` | Any other console message from the page, with file and line. |
