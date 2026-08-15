# Building the Windows installer

Produces a setup `.exe` that installs Arelis on a machine that has never had Python.

## Build it

```powershell
python win-installer\build.py
```

Any Python 3.11 or newer will do as the *build* interpreter; it is only used to build the
arelis wheel and to place a pinned pip into the tree. The interpreter that gets
**shipped** is downloaded, and is not the one you run this with.

Roughly four minutes cold, two warm, plus another few if Inno Setup is installed and the
setup `.exe` gets compiled.

Useful flags:

| Flag | What it does |
| --- | --- |
| `--no-installer` | Stop at the verified tree. The tree is the part that has to be right. |
| `--no-prune` | Keep all of Qt. Four times the size, for comparing behaviour when something works unpruned and not pruned. |
| `--measure-only` | Report the size of an existing tree and exit. |
| `--keep-tree` | Reuse `dist/Arelis` instead of unpacking a clean interpreter. |

### Optional: the setup .exe

Everything above works without Inno Setup; you just get a directory instead of an
installer. To get the `.exe`:

```powershell
winget install -e --id JRSoftware.InnoSetup
```

## What it produces

`win-installer/dist/Arelis/` — around **640MB**, a directory that runs Arelis with
nothing installed and nothing on PATH. Copy it anywhere and it works.

`win-installer/dist/Arelis-<version>-win64-setup.exe` — the same tree, compressed with
solid LZMA2, installing per-user into `%LOCALAPPDATA%\Programs\Arelis`.

Where the 640MB goes, largest first: Playwright's browser-automation driver (107MB), Qt
(98MB, down from 634MB), PyAV's FFmpeg (63MB), CTranslate2 for speech recognition
(60MB), ONNX Runtime (43MB), NumPy (51MB with its BLAS), pandas (30MB), sherpa-onnx
(28MB), espeak-ng for text-to-speech (18MB). That is the cost of running speech
recognition, speech synthesis, a browser and dataframes locally instead of sending
anything to a server, which is the entire point of the program.

## Changing dependencies

The installer does not install from `pyproject.toml`. It installs from
`requirements-win-amd64-cp314.txt`, which pins all 76 packages with `==` and a SHA-256
each, and is installed with `--require-hashes`.

After adding or removing a dependency:

```powershell
python win-installer\lock.py      # regenerate
python -m pytest                  # run the suite against what it produced
```

`lock.py --check` runs in CI. It is offline and does **not** re-resolve, so it cannot go
red because an unrelated project published a release; it checks that everything declared
is present and that every line is pinned and hashed.

Taking new upstream versions is meant to be a deliberate act with a commit attached. The
first time this lock was generated, resolving picked ten packages newer than the ones the
test suite had actually run against.

## Why it is built this way

**A real interpreter, not a frozen executable.** Arelis registers Windows scheduled
tasks that relaunch it as `pythonw.exe -m arelis --run-job <id>`. A PyInstaller or Nuitka
executable has no `-m`, so freezing would stop every job a user already has — silently,
because a scheduled task that fails shows nobody anything.

**CPython 3.14.** Python 3.12's last Windows binary was 3.12.10 in April 2025; every
release since is source only, so shipping 3.12 would mean shipping an interpreter that
can never get another security fix in a form we can redistribute. 3.13 leaves its bugfix
phase within months. 3.14 gets official Windows builds into late 2027.

**Verified, not merely built.** A build that exits zero having produced a tree that
cannot start is worse than one that fails, because the failure arrives on somebody
else's machine. So `build.py` finishes by running what it built: every Qt module the
codebase imports, one import per declared dependency, a real `QApplication` offscreen,
both entry points in a subprocess, and `scripts/installed_smoke.py` under the bundled
interpreter. This is also the only reason the Qt prune is defensible — a wrong entry in
it fails the build.

## The installer is not signed

There is no code-signing certificate, so Windows SmartScreen will warn on first download
until enough people have installed it to build a reputation. That warning is correct and
you should not tell anyone to ignore warnings in general.

What a cautious person can check instead: `build.py` prints the SHA-256 of the setup
`.exe`, and releases publish it. Compare with:

```powershell
Get-FileHash .\Arelis-0.1.0-win64-setup.exe -Algorithm SHA256
```

The bundled interpreter is verified during the build against the digest python.org
publishes in its own release manifest, and all 76 dependencies against the hashes in the
lock, so an installer that builds at all is built from known bytes.

## Installing and uninstalling

Per-user, into `%LOCALAPPDATA%\Programs\Arelis`, with no UAC prompt. Arelis is a
single-user program: its data root, its scheduled tasks and its OAuth tokens all belong
to one person, so a machine-wide install would be a machine-wide program with per-user
everything.

Uninstall removes the program and **deregisters every scheduled task Arelis created**,
which is the one thing an uninstaller here has to do beyond deleting files — a task holds
an absolute path, so removing the directory alone leaves Windows waking on a timer to run
something that is gone.

Uninstall deliberately leaves `%LOCALAPPDATA%\Arelis` alone. That is conversations,
memory, saved jobs, OAuth tokens and downloaded models: the user's data, not the
program's. Reinstalling picks it back up.
