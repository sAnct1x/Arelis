# Arelis

Arelis is a personal research assistant for Windows. She runs entirely
on your PC. There's no account, no cloud API, and no data leaving your
machine. She thinks using a local model through
[Ollama](https://ollama.com/download), searches the web, drives her
own browser, and keeps longer projects organized in named rooms.
Anything that writes a file or sends a message waits for your approval
first.

**Overview video:** https://youtu.be/TWZqnyHlh4M • **Download:** [v0.3.0](https://github.com/sAnct1x/Arelis/releases/latest)

## What it does

- Search the web and read pages
- Drive her own browser window (separate from yours)
- Work in folders you approve, keeping projects organized in rooms
- Listen and speak (wake word, voice conversations, dictation)
- Handle images (look at them, edit them, generate with local ComfyUI)
- Manage email, texting through your Android phone, and calendar (all opt-in)
- Run scheduled jobs, set reminders, track facts and tasks
- Work with documents (PDF, Word, Excel, markdown)
- Handle math, unit conversions, charts, and code snippets

Mail, calendar, and texting stay off until you connect them. Everything
that writes or sends shows you an approval card first.

## What you need

- **Windows 10 or later** (64-bit)
- **Ollama** (downloads automatically if missing, ~1.4 GB)
- **A chat model** (downloads on first run - the recommended model is `qwen3.5:9b`)
- **8-16 GB graphics card** recommended for good performance
- **About 0.9 GB disk space** for the installed program (plus models)

Optional extras like voice, browser control, and the phone app can be
added later. The core program works without them.

## Quick start

**To install:** Download the latest installer from [GitHub releases](https://github.com/sAnct1x/arelis/releases/latest) (`Arelis-0.3.0-win64-setup.exe`, about 245 MB). Run it. The first time you open Arelis, she'll ask which folder she can use, then download Ollama and the chat model if needed. That's it.

If you tried an installer from 0.2.4 to 0.2.9, those were broken and never opened. 0.3.0 fixes that, so just run the new one.

**To run from source:** See [Running from source](#running-from-source) below.

**Note:** The installer isn't code-signed, so Windows SmartScreen will warn you the first time. That's normal. You can verify the download by checking the SHA-256 hash against the `.sha256` file in the release.

## About this project

I maintain Arelis. I'm a 4th-year astrophysics student at OSU.
Hobby project, spare time. It's been about a year of
on-and-off work, with updates coming in bursts around the school
calendar. Help and feedback are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for how to help.

Arelis is licensed under AGPL-3.0-or-later. How the code is put
together is in [architecture.md](docs/architecture.md).

## Privacy and safety

Nothing leaves your machine unless you asked for it. No sign-up, no
analytics, no crash reports. Your conversations, contacts, and memory
are ordinary files on your disk that you can open, edit, or delete
anytime.

Network access only happens when you've asked for it: web search,
weather, mail, calendar, or your phone. An installed copy checks GitHub
once a day for updates (source checkouts don't). Set `updates.check: false` in your local settings
file (`config.local.yaml` in the data folder) to turn that daily check off.
Every host the program
can contact is pinned by a test, so adding a new destination fails the
build.

Anything risky (mail, texts, file writes, deletes) shows you an approval
card first. You can see and edit what's allowed without asking under
Settings → Allow. That's the default **sodium** theme. There's also
**filament (testing)** where speaking the request is the grant, but
deletes, payments, and running project scripts still ask.

## Installing

Download the latest setup file from [GitHub releases](https://github.com/sAnct1x/arelis/releases/latest): `Arelis-0.3.0-win64-setup.exe` (about 245 MB download, about 0.9 GB installed). Run it. It installs per-user into `%LOCALAPPDATA%\Programs\Arelis`, so no administrator prompt.

### First run

The installer bundles voice support and the browser, but not the chat
model or voice weights. On first launch:

1. She'll ask which folder she can use (she can only read and write inside this folder)
2. If Ollama isn't installed, she'll download it (~1.4 GB)
3. She'll download the chat model (recommended: `qwen3.5:9b` for 8-16 GB graphics cards)
4. Voice weights download in the same step (Sherpa, Kokoro, Silero)

Once the model is ready, you'll see **say "hey arelis"** in the window.
That's it.

### Verifying the download

The installer isn't code-signed, so SmartScreen will warn you. That's
normal. To verify your download wasn't corrupted, check the SHA-256:

```powershell
Get-FileHash .\Arelis-0.3.0-win64-setup.exe -Algorithm SHA256
Get-Content .\Arelis-0.3.0-win64-setup.exe.sha256
```

The two hashes should match. Both files are in the release.

You can launch Arelis from the Start menu once installed. Only the
installed copy checks for updates; source checkouts don't. An install
won't touch your source checkout's profile if you have one - they keep
separate records.

For details on models, see [models.md](docs/models.md). For how the
installer is built, see [win-installer/README.md](win-installer/README.md).

## Running from source

You'll need [Python 3.11+](https://www.python.org/downloads/) and
[Ollama](https://ollama.com/download). Then:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

This installs the core program plus science tools (CAS, units, charts,
arXiv, Horizons). To add optional features:

```powershell
pip install -e ".[voice]"      # talking and listening
pip install -e ".[browser]"    # her own browser window
playwright install chromium    # required after installing browser extra
pip install -e ".[spatial]"    # hand tracking in Reality (source only)
pip install -e ".[astro]"      # 3D solar system (source only)
```

### Running it

```powershell
.\scripts\run_ui.ps1
```

Or just `arelis` with the virtual environment active. For terminal
mode: `arelis --cli`. To run in the background for phone messages:
`.\scripts\run_core.ps1`.

To create a desktop shortcut for the dev build:

```powershell
.\scripts\install_desktop_shortcut.ps1
```

This creates **Arelis (dev)**, which won't overwrite an installed copy's
shortcut.

## Where everything lives

On first launch, she'll ask which folder she's allowed to use. She can
create and edit files inside that folder, and nowhere else.

| What | Where | Notes |
|---|---|---|
| The program | `%LOCALAPPDATA%\Programs\Arelis` | Gets replaced whenever she updates |
| Your records | `%LOCALAPPDATA%\Arelis` | Profile, contacts, mail login, memory, settings, logs |
| Her workspace | wherever you chose | The only place she can read and edit files. Ctrl+2 is the desk: notes you kept and files she wrote |

Your contacts and passwords are kept separate from anything a language
model could delete on its own. They don't live in the workspace
folder. Updating the program won't wipe out your records, either. And
if two people share one PC, each gets their own, unrelated set of
records.

If you're running from source, records and workspace default to the
repository itself (`data/`). An installed copy and a source checkout
on the same machine never share a profile. You can point a checkout at
a sandbox location instead using `ARELIS_DATA_DIR`:
`scripts\run_dev_ui.ps1` does exactly this, using
`%LOCALAPPDATA%\Arelis-dev`.

Uninstall from Apps & Features always removes the program and scheduled
tasks. It asks whether to delete records too: **No** keeps
`%LOCALAPPDATA%\Arelis` for a later reinstall. **Yes** also takes her
runtime folder and the default workspace, and never a source checkout
or a system Ollama install.

## Optional: mail, phone, calendar

These stay off until you connect them. Until then, they're hidden from
the **Systems** view, the related tools aren't offered, and if you ask
her to use them, she'll tell you she can't.

| Copy this | To this | For |
|---|---|---|
| `data/profile.example.yaml` | `data/profile.yaml` | Your name, where you live |
| `data/contacts.example.yaml` | `data/contacts.yaml` | People she can text or email |
| `data/secrets.example.yaml` | `data/secrets.yaml` | Mail login, phone pairing, calendar |

Mail has no Settings tab of its own. Put the address and app password
under Settings, Notify, or in the `email:` block of `secrets.yaml`.
(That's a Gmail app password, not your actual Google password.) For phone, go to Settings → Notify and
scan the QR code. See [notify-inbound.md](docs/notify-inbound.md).
For calendar, see [calendar-oauth.md](docs/calendar-oauth.md). Note
that scheduled jobs need mail set up first (details in
[jobs.md](docs/jobs.md)).

## Using Arelis

**The window.** Sodium is the default face. Type in the box to chat.
Once you send a message, you'll see the full workbench: chat,
composer, and docks for thinking, files, history, contacts, and
notifications. She follows your Windows display scale (1080p, 2K,
4K, mixed monitors) the same way other desktop apps do; Settings →
window → Interface scale is an extra zoom if you want one. **filament
(testing)** under View → themes is a checkout experiment that wants
a row of desks: three monitors is the intended layout. Press **F1**
any time for shortcuts and the current version.

**Rooms.** The main chat is for everyday questions. Anything you want
to pick back up later belongs in a **room**: a name, a folder, and
its own thread. `/room physics` takes you in, `/leave` takes you out,
and the last room you were in reopens the next time you launch her.
More in [rooms.md](docs/rooms.md).

**Roles.** There are two modes: `/role fast` and `/role research`.
File and git work always stays on Fast. Once setup is done, both modes
actually use the same model (`qwen3.5:9b`, unless you picked something
else). Research just means a longer reasoning loop, not a bigger
model. See [models.md](docs/models.md).

**Optional features:**
- **Voice:** Wait until the idle line says **say "hey arelis"**, not **getting the ear…**. A bare name still will not wake her. `Ctrl+Shift+M` starts a conversation, `Ctrl+M` is for dictation. See [voice-wake.md](docs/voice-wake.md).
- **Her browser:** Not your everyday Chrome: her own separate window that you can watch. She'll never type a password or click Book, Pay, or Checkout. See [browser-control.md](docs/browser-control.md).
- **Phone app:** One sideloaded **Arelis** app, paired by scanning the QR code in Settings → Notify. Google Messages stays your everyday messenger. She sends texts from your SIM only after you approve the card. If the PC is off, the phone keeps its own conversation going; if you installed Gemma during pairing (~2.6 GB), she can keep talking on-device, and those messages sync back once the PC is up again. See [notify-inbound.md](docs/notify-inbound.md).
- **Mail, calendar, texting:** All stay off until you connect them. Configuration lives in `data/secrets.yaml`. See [calendar-oauth.md](docs/calendar-oauth.md) and the optional extras section above.
- **Jobs:** Found under the calendar tile (`Ctrl+7`). Set a prompt and a time, and she'll email you the answer. Requires mail to be set up. See [jobs.md](docs/jobs.md). "Remind me in 20 minutes" is a timer, not a job.

**Memory.** Managed under Settings → Memory. Since 0.3.0, before an
in-app upgrade she copies your memory and a few settings files into
`pre-<version>/` next to her data folder (never passwords or tokens)
and keeps the newest two. A failed copy stops the update. Upgrading
from 0.2.9 to 0.3.0 itself is not covered, so copy your data folder by
hand first. Daily dated memory copies stay off. See
[backups.md](docs/backups.md).

Type `/tools` in the chat for the full list of what she can do.

## Source-only features

If you're running from source, you get the 3D solar system and Earth
view inside Reality ([earth.md](docs/earth.md)). Installed copies still
get Reality as a room (chat, CAS, Horizons all work), but the 3D visuals
don't ship in the installer.

## Known limitations

Test coverage is good for most features, but voice timing, the phone
app, and image generation have mainly been tested on my hardware. If
something behaves oddly on yours, open an issue. Current release is
**0.3.0** - see [whats-new.md](docs/whats-new.md) for changes.

## Common issues

- Windows SmartScreen warns you the first time you open the installer. I didn't sign it, so that warning is normal for this file. The check that the download itself is intact is up in Verifying the download.
- If Ollama does not download on its own, check that this PC is online and that the disk has room, then press Try again. If an Ollama window is already open, finish that first. You can also install Ollama yourself from [Ollama](https://ollama.com/download), then open Arelis again. She uses the copy already on the PC.
- The chat model is a big download. The setup window says so while it comes down. She will not close that window while a download is still running. If nothing new shows up for about an hour, that attempt ends and Try again appears. Check that the PC is online and that the disk has room, then press Try again. If you do not want to wait that out, end Arelis in Task Manager and open her again. She asks again. She only remembers the model after the download finishes.
- When something goes wrong, she writes a log on this PC. I never send that log anywhere. If you installed her, the log sits with her records. If you are running her from this project, the log sits with the project.
- Still stuck? Open the [issue forms](https://github.com/sAnct1x/Arelis/issues/new/choose). One form is for a first open that went wrong, and one is for other bugs. Questions go in [Discussions](https://github.com/sAnct1x/Arelis/discussions).

## Further reading

| Document | What's in it |
|---|---|
| [Overview video](https://youtu.be/TWZqnyHlh4M) | Demo and walkthrough on the [Arelis Lab channel](https://www.youtube.com/@ArelisLab) |
| [whats-new.md](docs/whats-new.md) | 0.3.0 checkout and installer |
| [rooms.md](docs/rooms.md) | Named project spaces |
| [jobs.md](docs/jobs.md) | Timed prompts, emailed |
| [models.md](docs/models.md) | Which models, and why |
| [voice-wake.md](docs/voice-wake.md) | Hey Arelis, talk, dictate |
| [browser-control.md](docs/browser-control.md) | Her browser |
| [notify-inbound.md](docs/notify-inbound.md) | Phone app |
| [calendar-oauth.md](docs/calendar-oauth.md) | Connecting a calendar |
| [architecture.md](docs/architecture.md) | How the code is organized |
| [earth.md](docs/earth.md) | Earth view inside Reality (source checkout) |
| [telemetry.md](docs/telemetry.md) | Logs, on your disk |
| [win-installer/README.md](win-installer/README.md) | Building the installer |

## Contributing

Questions about setting up or using Arelis go in
[Discussions](https://github.com/sAnct1x/Arelis/discussions), and so do
ideas. Bugs go in [Issues](https://github.com/sAnct1x/Arelis/issues).

See [CONTRIBUTING.md](CONTRIBUTING.md). Found a security hole? Tell me
privately, per [SECURITY.md](SECURITY.md). Don't open a public issue
for that.

Nothing that identifies a real person should ever go into this
repository. There's a test that enforces it.

## License

[GNU Affero General Public License, version 3 or later](LICENSE).

You're free to use it, read it, change it, and share it. If you share
a modified version (including by running it as a service other people
connect to), you need to make your changes available under the same
license.
