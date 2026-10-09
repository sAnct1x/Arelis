# Building the Mac app

An unsigned `Arelis.app` inside `Arelis-<version>.dmg`. Not a frozen blob:
a real interpreter, so `python -m arelis` still works.

Do not run this unless you mean to build an app. It downloads CPython and
the locked libraries. It only runs on macOS.

## Build it

```bash
python mac-installer/build.py
```

Any Python 3.11 or newer will do as the build interpreter. The interpreter
that gets shipped is downloaded. It is not the one you run this with.

| Flag | What it does |
| --- | --- |
| `--no-dmg` | Stop at `Arelis.app`. Do not run `hdiutil`. |
| `--keep-tree` | Reuse the interpreter already in `dist/Arelis.app`. |

The disk image is made with `hdiutil`. Nothing is signed or notarized.

## What it produces

`mac-installer/dist/Arelis.app` runs on an Apple silicon Mac that has never
had Python. The interpreter lives at `Contents/Resources/python`. The Dock
launcher is `Contents/MacOS/Arelis`, and it runs that interpreter with
`-m arelis`.

`mac-installer/dist/Arelis-<version>.dmg` is that app, compressed.

## Why it is built this way

**A real interpreter, not PyInstaller or Briefcase.** Those freeze an
executable with no `-m`. Jobs that relaunch Arelis as `python -m arelis`
would stop. python-build-standalone is a relocatable CPython, pinned by
release and sha256 the same way the Windows embeddable zip is pinned.

**CPython 3.13, not 3.14.** The Windows installer ships 3.14.7. On Mac,
onnxruntime has no cp314 wheel (1.30.0 included), and voice is part of the
installer extra. 3.13.16 is the newest 3.13 in the pinned standalone
release. Qt is still PySide6 6.11.2, under the same `<6.12` cap.

**The lock.** `requirements-macos-arm64-cp313.txt` pins every package with
`==` and a sha256. Regenerate with `python mac-installer/lock.py`, then run
the tests. `--check` is offline and does not re-resolve.

## Opening an unsigned app

The first time, right-click (or Control-click) Arelis and choose Open, then
Open again in the warning. Or System Settings, Privacy and Security, Open
Anyway.

## Updates

An installed Mac copy can notice a newer GitHub release. It shows that
notice with a link to the release page. It does not download or run
anything. Windows still downloads the setup file. Linux is unchanged.
