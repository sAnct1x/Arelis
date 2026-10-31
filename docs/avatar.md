# The 3D avatar

Arelis can show her face as a 3D figure drawn with three.js inside the app. The scene
runs from files that ship with Arelis. Nothing is loaded from the internet.

## Where the model file goes

The model is not part of the download. Put it here:

```
%LOCALAPPDATA%\Arelis\avatar\ellah.glb
```

Create the `avatar` folder if it is not there. Restart Arelis after adding the file.

To use a file somewhere else, set the `ARELIS_AVATAR_GLB` environment variable to its
full path before starting Arelis.

If you run Arelis from a copy of its source code, it first looks in that copy's avatar folder,
then in the avatar folder of the installed app (in your local app data). If neither has the
file, the log lists the places it checked.

## What she does

- Thinking, speaking and done each have their own look.
- While she speaks, her mouth and jaw follow the voice.
- When the microphone is listening, the scene is told so.
- She blinks on her own.
- Click her while she speaks to stop her, the same as before.

## When you see the painted face instead

Arelis goes back to the painted face whenever the 3D view cannot run:

- no model file at the path above,
- the 3D engine (QtWebEngine) is not available,
- the graphics card or driver cannot run WebGL,
- the scene reports an error while loading or running,
- GPU space is on (`ARELIS_SOLAR_GL=1`), which cannot share the process with it.

The log line `painted face in use:` or `web avatar off, painted face kept:` says which.
To turn the 3D view off on purpose, set `ARELIS_WEB_AVATAR=0`.
