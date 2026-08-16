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

**Nothing is started through a pip launcher.** Both shortcuts, the "start now" checkbox,
the update relaunch and the uninstall hook all run `{app}\python[w].exe -m arelis`. pip
writes the absolute path of the installing interpreter into every `.exe` launcher it
generates, so the shipped `arelis.exe` pointed at the build directory — a path that exists
on one computer. That is nearly invisible: on the machine that built it the launcher works
and runs the *build tree*, so it passes every check while testing the wrong copy.

There is no relocatable fix. `#!..\python.exe` is not understood, and a bare `#!python.exe`
is resolved against `PATH` — measured here, that started an unrelated Python 3.11 from
`%LOCALAPPDATA%\Programs` and imported `arelis` out of a source checkout, which is worse
than failing. A correct launcher needs the install directory, which a per-user install does
not know until the user picks it. So `build.py` deletes them, writes `Scripts\arelis.cmd`
and `arelisw.cmd` shims that find their own interpreter through `%~dp0`, and fails the build
if a `.exe` launcher reappears or if any shipped file names the directory it was built in.

**CPython 3.14.** Python 3.12's last Windows binary was 3.12.10 in April 2025; every
release since is source only, so shipping 3.12 would mean shipping an interpreter that
can never get another security fix in a form we can redistribute. 3.13 leaves its bugfix
phase within months. 3.14 gets official Windows builds into late 2027.

**Verified, not merely built.** A build that exits zero having produced a tree that
cannot start is worse than one that fails, because the failure arrives on somebody
else's machine. So `build.py` finishes by running what it built: every Qt module the
codebase imports, one import per declared dependency, a real `QApplication` offscreen,
every way of launching it in a subprocess, a scan for files naming this machine, and
`scripts/installed_smoke.py` under the bundled interpreter. This is also the only reason the
Qt prune is defensible — a wrong entry in it fails the build.

## Working on Arelis while using Arelis

Once you have installed it, there are two copies on the machine and one set of data. That
is worth being deliberate about.

Once you have installed it, there are two copies on the machine. They do not share a data
root, and that is worth knowing precisely, because installing does **not** carry your
profile over.

| | The one you use | The one you edit |
| --- | --- | --- |
| Program | `%LOCALAPPDATA%\Programs\Arelis` | this checkout |
| Data | `%LOCALAPPDATA%\Arelis` | the repository root |
| With `run_dev_ui.ps1` | — | `%LOCALAPPDATA%\Arelis-dev` |
| Launched by | the `Arelis` shortcut | `Arelis (dev)`, or `scripts\run_ui.ps1` |
| Safe to break | no | yes |

`user_data_dir()` sends a checkout to the repository root, on two markers that a wheel
cannot have. So a fresh install opens as a stranger's Arelis: no contacts, no persona, no
memory, no jobs. Moving your own profile into `%LOCALAPPDATA%\Arelis` is a deliberate,
one-time copy, not something the installer does.

That separation already keeps the installed copy safe from the checkout. What
`run_dev_ui.ps1` adds is separating the checkout from itself, because running from the
repository makes the repository the profile — `data\profile.yaml`, `data\secrets.yaml`,
`data\memory.db` and `data\jobs.yaml` there are the real ones.

The failure that actually bites is scheduled jobs. A task holds one absolute path and is
named after the job, so both copies want the same task. Nothing thrashes in steady state —
each copy records the launcher it registered with under its own data root, and
`repoint_moved_tasks_on_launch()` repoints only when that record disagrees with itself. But
a copy claims every task in its `jobs.yaml` at two moments: its first launch with no record
yet, which is what a fresh install is, and whenever you create or edit a job in it. Neither
copy can see the other, so nothing arbitrates. Editing a job in the checkout moves your
real 23:00 run into the working tree.

`ARELIS_DATA_DIR` settles that structurally rather than by care: jobs are read from
`jobs.yaml` inside the data root, so a sandbox without one has nothing to claim at either
moment.

The sandbox starts empty — no conversations, memory, contacts, persona tuning, jobs or
tokens — which is the point twice over. It is safe to break, and it is the only way to see
the first run a stranger gets. Delete the directory whenever you want that first run back.

### Promoting your changes

```powershell
python win-installer\build.py --install
```

Builds, verifies, compiles and installs over the existing copy. Because `arelis.iss` pins
`AppId`, that is an upgrade rather than a second install: same directory, same Start Menu
entry, one row in Apps & Features, and `%LOCALAPPDATA%\Arelis` untouched.

## Updating itself

An installed Arelis asks GitHub once a day whether a newer release exists, offers it, and on
a yes downloads the setup `.exe`, checks it against the published digest, installs it
silently and reopens. Your data is never involved: the upgrade replaces `{app}` and
`%LOCALAPPDATA%\Arelis` is not touched.

```
arelis --check-update
```

reports what the app would find, and installs nothing. Useful when something about updating
is already not working.

The pieces, and where the decisions live:

| | |
| --- | --- |
| `arelis/update.py` | the whole policy, with no Qt in it, so it is tested without a display |
| `arelis/ui/update_prompt.py` | threads, the question, a progress bar, and quitting at the end |
| `arelis.iss` `[Code]` | reads `/relaunch=yes` so a silent upgrade reopens the app |

Four decisions worth knowing:

**Only copies the installer produced.** Windows, not a source checkout, and a tree with
`unins000.exe` at its root. The last is not paranoia: pip-installing Arelis into a
virtualenv also isn't a checkout, and downloading a 150 MB setup `.exe` to run over
somebody's venv is a rude way for them to discover that.

**Published releases only.** It reads `releases/latest`, which excludes drafts and
prereleases — and the release workflow publishes drafts. So tagging builds an installer and
offers it to nobody; pressing publish on GitHub is what ships it. The staging area is the
default and no flag can skip it by accident.

**The digest is checked, and is not a signature.** The `.sha256` comes from the same release
as the `.exe`, so whoever could replace one could replace the other. What it catches is what
actually happens: a truncated or corrupted download. The trust anchor is HTTPS to
`api.github.com`. A mismatch deletes the file rather than leaving 150 MB of
something-unexpected named as though it were an installer.

**Quitting is part of the update.** An upgrade replaces the interpreter and DLLs of the
process asking for it, and Windows will not allow that while they are open. `CloseApplications=yes`
handles the core process; `/relaunch=yes` is what brings the window back, because the
"Start Arelis now" checkbox is skipped in a silent install.

What it sends: one unauthenticated `GET`, carrying a `User-Agent` naming the version. That
is unavoidable — asking "is there anything newer than this" requires saying what this is.
It is on the egress allowlist in `tests/test_egress.py` with that reasoning.

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
