# Building the Windows installer

A setup `.exe` that puts Arelis on a machine that has never had Python.
Not a frozen blob: a real interpreter, so scheduled jobs can still say
`pythonw.exe -m arelis`.

Do not run this unless you mean to build a tree. The live install at
`%LOCALAPPDATA%\Programs\Arelis` is a different copy.

## Build it

```powershell
python win-installer\build.py
```

Any Python 3.11 or newer will do as the *build* interpreter. The
interpreter that gets **shipped** is downloaded. It is not the one you
run this with.

Roughly four minutes cold, two warm, plus another few if Inno Setup is
installed and the setup `.exe` gets compiled.

| Flag | What it does |
| --- | --- |
| `--no-installer` | Stop at the verified tree. |
| `--no-prune` | Keep all of Qt. Four times the size. |
| `--measure-only` | Report the size of an existing tree and exit. |
| `--keep-tree` | Reuse `dist/Arelis` instead of unpacking a clean interpreter. |

Everything above works without Inno Setup. You just get a directory. To
get the `.exe`:

```powershell
winget install -e --id JRSoftware.InnoSetup
```

## What it produces

`win-installer/dist/Arelis/` is around 640 MB. A directory that runs
Arelis with nothing installed and nothing on PATH.

`win-installer/dist/Arelis-0.2.5-win64-setup.exe` is the same tree,
compressed, installing per-user into `%LOCALAPPDATA%\Programs\Arelis`.

Where the 640 MB goes, largest first: Playwright's driver, Qt, PyAV's
FFmpeg, CTranslate2, ONNX Runtime, NumPy, pandas, sherpa-onnx,
espeak-ng. That is the cost of speech, a browser, and dataframes on this
PC instead of a server.

## Changing dependencies

The installer does not install from `pyproject.toml`. It installs from
`requirements-win-amd64-cp314.txt`, which pins every package with `==`
and a SHA-256, installed with `--require-hashes`.

After adding or removing a dependency:

```powershell
python win-installer\lock.py
python -m pytest
```

`lock.py --check` runs in CI. It is offline and does not re-resolve, so
it cannot go red because an unrelated project published a release.
Taking new upstream versions is a deliberate commit.

## Why it is built this way

**A real interpreter, not a frozen executable.** Arelis registers
Windows scheduled tasks that relaunch it as `pythonw.exe -m arelis
--run-job <id>`. A frozen executable has no `-m`, so freezing would stop
every job a user already has, silently.

**Nothing is started through a pip launcher.** pip writes the absolute
path of the installing interpreter into every `.exe` launcher it
generates. On the machine that built it, that launcher works and runs
the *build tree*, so it passes every check while testing the wrong copy.
`build.py` deletes those launchers and writes `Scripts\arelis.cmd` and
`arelisw.cmd` shims that find their own interpreter.

**CPython 3.14.** Official Windows builds into late 2027. 3.12's last
Windows binary was 3.12.10.

**Verified, not merely built.** `build.py` finishes by running what it
built: Qt imports, one import per declared dependency, a real
`QApplication` offscreen, every launch path, a scan for files naming
this machine, and `scripts/installed_smoke.py` under the bundled
interpreter.

## Working on Arelis while using Arelis

Once you have installed it, there are two copies on the machine. They
do not share a data root. Installing does not carry your profile over.

| | The one you use | The one you edit |
| --- | --- | --- |
| Program | `%LOCALAPPDATA%\Programs\Arelis` | this checkout |
| Data | `%LOCALAPPDATA%\Arelis` | the repository root |
| With `run_dev_ui.ps1` | (n/a) | `%LOCALAPPDATA%\Arelis-dev` |
| Launched by | the `Arelis` shortcut | `Arelis (dev)`, or `scripts\run_ui.ps1` |
| Safe to break | no | yes |

`user_data_dir()` sends a checkout to the repository root. A fresh
install opens as a stranger's Arelis: no contacts, no persona, no
memory, no jobs. Moving your own profile into `%LOCALAPPDATA%\Arelis` is
a deliberate, one-time copy.

The failure that actually bites is scheduled jobs. A task holds one
absolute path and is named after the job, so both copies want the same
task. Editing a job in the checkout can move a live 7pm digest into
the working tree. `ARELIS_DATA_DIR` settles that: jobs are read from
`jobs.yaml` inside the data root, so a sandbox without one has nothing
to claim.

`run_dev_ui.ps1` gives the checkout a sandbox at
`%LOCALAPPDATA%\Arelis-dev`. Empty on purpose. Safe to break. The only
way to see the first run a stranger gets.

### Promoting your changes

```powershell
python win-installer\build.py --install
```

Builds, verifies, compiles, and installs over the existing copy. Same
directory, same Start Menu entry, `%LOCALAPPDATA%\Arelis` untouched.

## Updating itself

An installed Arelis asks GitHub once a day whether a newer release
exists, offers it, and on a yes downloads the setup `.exe`, checks it
against the published digest, installs it silently, and reopens. Your
data is never involved.

```
arelis --check-update
```

reports what the app would find, and installs nothing.

Four decisions:

**Only copies the installer produced.** Windows, not a source checkout,
and a tree with `unins000.exe` at its root. pip-installing Arelis into
a virtualenv also isn't a checkout.

**Published releases only.** It reads `releases/latest`, which excludes
drafts and prereleases. Tagging builds an installer and offers it to
nobody. Pressing publish on GitHub is what ships it.

**The digest is checked, and is not a signature.** The `.sha256` comes
from the same release as the `.exe`. What it catches is a truncated or
corrupted download. The trust anchor is HTTPS to `api.github.com`.

**Quitting is part of the update.** An upgrade replaces the interpreter
and DLLs of the process asking for it. Windows will not allow that while
they are open.

What it sends: one unauthenticated `GET`, carrying a User-Agent naming
the version. That is on the egress allowlist in `tests/test_egress.py`.

## The installer is not signed

There is no code-signing certificate, so Windows SmartScreen will warn
on first download until enough people have installed it to build a
reputation. That warning is correct. Do not tell anyone to ignore
warnings in general.

What a cautious person can check instead: `build.py` prints the SHA-256
of the setup `.exe`, and releases publish it.

```powershell
Get-FileHash .\Arelis-0.2.5-win64-setup.exe -Algorithm SHA256
```

The bundled interpreter is verified during the build against the digest
python.org publishes. Dependencies are checked against the hashes in the
lock.

## Installing and uninstalling

Per-user, into `%LOCALAPPDATA%\Programs\Arelis`, with no UAC prompt.

Uninstall always removes the program and deregisters every scheduled
task Arelis created. A task holds an absolute path, so removing the
directory alone leaves Windows waking on a timer to run something that
is gone.

It then asks whether to delete data too. **No** is the default, so a
reinstall still finds conversations, memory, saved jobs, OAuth tokens,
and downloaded models under `%LOCALAPPDATA%\Arelis`.

**Yes** also removes:

| Path | What it is |
| --- | --- |
| `%LOCALAPPDATA%\Arelis` | Profile, chats, secrets, models, her Chrome, Playwright browsers |
| `%LOCALAPPDATA%\Arelis-runtime` | Ollama setup we downloaded (not a system Ollama install) |
| `%LOCALAPPDATA%\Arelis-dev` | Checkout sandbox from `run_dev_ui.ps1` |
| `Documents\Arelis` | Default workspace, **only if it is not a source checkout** |

A scripted full removal: `unins000.exe /SILENT /wipe=yes`.

Never removed: a system Ollama install, `%USERPROFILE%\.ollama`, or
this repository.
