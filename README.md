# Arelis

Arelis is a personal research assistant that runs entirely on your
Windows PC. She thinks using a local model through
[Ollama](https://ollama.com/download), so there's no account to create
and nothing goes to a paid chat API.

You can talk to her through a desktop window, the terminal, or a phone
app on the same Wi-Fi network. Point her at a folder to work in, and
she can search the web, drive her own browser, and keep longer projects
organized in named **rooms**. Mail, texting, and calendar access stay
switched off until you connect them yourself, and anything that writes
a file or sends a message will wait for your go-ahead first.

The published installer is **0.2.4**. If you build from source,
you also get **Reality** — a room with a 3D solar system and an Earth
view — but that doesn't ship with the installer.

Arelis is licensed under AGPL. If you're curious how the code is
organized, see [architecture.md](docs/architecture.md).

## Privacy

Nothing about you leaves this machine unless you explicitly asked her
to send it somewhere.

There's no sign-up, no analytics, and no crash reports being phoned
home. Logs live on your disk. Your conversations, contacts, and memory
are just ordinary files — you can open them, edit them, or delete them
whenever you want.

She only touches the network when you've asked her to: for a search,
the weather, mail, a calendar you've connected, or your own phone. The
one exception is that an installed copy checks GitHub once a day to see
if there's a newer version — a source checkout never does this. Every
host she's allowed to talk to is pinned by a test, so if something
tries to add a new destination, the build simply fails.

Anything risky pauses on an **allow / deny** card before it happens.
Mail and texts always show you the exact message before it goes out,
and she won't send either while you're away. You can see (and edit)
everything she's allowed to do without asking under Settings → Allow.

## Installing

You'll need Windows 10 or later, 64-bit.

Grab the latest setup file from
[GitHub releases](https://github.com/sAnct1x/arelis/releases/latest).
The current file is `Arelis-0.2.4-win64-setup.exe` — about 155 MB to
download, roughly 640 MB once installed. It installs per-user into
`%LOCALAPPDATA%\Programs\Arelis`, so you won't get an administrator
prompt.

It's **not code-signed**, so SmartScreen will warn you the first time
you run it — that's just Windows doing its job, not a sign anything's
wrong. Worth checking the SHA-256 against the installer, though:

```powershell
Get-FileHash .\Arelis-0.2.4-win64-setup.exe -Algorithm SHA256
Get-Content .\Arelis-0.2.4-win64-setup.exe.sha256
```

The two hashes should match — that just confirms your download wasn't
corrupted, not that it's been signed by anyone. Both files ship
together in the same release.

The installer bundles voice support and her browser, but not the
models themselves. The first time you open her, she'll ask which folder
she's allowed to read and modify, then which model to download. You
can go with the recommended one, or pick Gemma or DeepSeek instead —
just note that Fast and Research modes share whichever model you
choose, so it's one at a time. If [Ollama](https://ollama.com/download)
isn't already on your system, she'll grab that first (about 1.4 GB),
then the model itself. The recommended model can already read images
on its own; a separate vision model only gets downloaded if you choose
one that can't.

If you're running an 8–16 GB graphics card, `qwen3.5:9b` is the usual
recommendation. If you're working from source, you can pull it
yourself:

```powershell
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
```

Ollama itself is shared system-wide, so if you've also got a 0.2.2
install on the same machine, it's still relying on Qwen2.5 7B / 14B /
Coder 7B — don't delete those models while that older copy is still
around. More detail in [models.md](docs/models.md).

You can launch **Arelis** from the Start menu once it's installed.
Only the installed copy checks for updates; a source checkout won't.
Installing also won't touch or copy any profile from this repository
— the two setups deliberately keep separate records.

Curious how the installer itself gets built? See
[win-installer/README.md](win-installer/README.md).

## Running from source

You'll need [Python 3.11+](https://www.python.org/downloads/) and
Ollama, then:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

The science tools (CAS, units, charts, arXiv, Horizons) are included
in that base install — there's no separate `science` extra. NASA APOD
and NASA ADS do need a free API key added to `data/secrets.yaml`,
though.

A few optional extras, depending on what you want:

```powershell
pip install -e ".[voice]"      # talking and listening
pip install -e ".[browser]"    # her own browser window
playwright install chromium
pip install -e ".[spatial]"    # hand tracking in Reality — source only
pip install -e ".[astro]"      # the 3D solar system — source only
```

Then start her up with:

```powershell
.\scripts\run_ui.ps1
```

Or just run `arelis` once your virtual environment is active. For the
terminal, use `arelis --cli`. If you want her running quietly in the
background for phone messages, without opening a window, use
`.\scripts\run_core.ps1`.

Want a desktop icon for a checkout? Run:

```powershell
.\scripts\install_desktop_shortcut.ps1
```

That creates a shortcut named **Arelis (dev)**, so it won't overwrite
the shortcut from an installed copy.

## Where everything lives

On first launch, she'll ask which folder she's allowed to use. She can
create and edit files inside that folder — and nowhere else.

| What | Where | Notes |
|---|---|---|
| The program | `%LOCALAPPDATA%\Programs\Arelis` | Gets replaced whenever she updates |
| Your records | `%LOCALAPPDATA%\Arelis` | Profile, contacts, mail login, memory, settings, logs |
| Her workspace | wherever you chose | The only place she can read and edit files. Ctrl+2 is the desk: notes you kept and files she wrote |

Your contacts and passwords are kept separate from anything a language
model could delete on its own — they don't live in the workspace
folder. Updating the program won't wipe out your records, either. And
if two people share one PC, each gets their own, unrelated set of
records.

If you're running from source, records and workspace default to the
repository itself (`data/`). An installed copy and a source checkout
on the same machine never share a profile. You can point a checkout at
a sandbox location instead using `ARELIS_DATA_DIR` —
`scripts\run_dev_ui.ps1` does exactly this, using
`%LOCALAPPDATA%\Arelis-dev`.

## Optional: mail, phone, calendar

These stay off until you connect them. Until then, they're hidden from
the **Systems** view, the related tools aren't offered, and if you ask
her to use them, she'll tell you she can't.

| Copy this | To this | For |
|---|---|---|
| `data/profile.example.yaml` | `data/profile.yaml` | Your name, where you live |
| `data/contacts.example.yaml` | `data/contacts.yaml` | People she can text or email |
| `data/secrets.example.yaml` | `data/secrets.yaml` | Mail login, phone pairing, calendar |

There's no Mail tab in Settings — mail is configured through the
`email:` block in `secrets.yaml` (that's a Gmail app password, not
your actual Google password). For phone, go to Settings → Notify and
scan the QR code — see [notify-inbound.md](docs/notify-inbound.md).
For calendar, see [calendar-oauth.md](docs/calendar-oauth.md). Note
that scheduled jobs need mail set up first — details in
[jobs.md](docs/jobs.md).

## Using her

**The window.** Just type in the box. Once you send a message, you'll
see the full workbench: chat, composer, and docks for thinking, files,
history, contacts, and notifications. Press **F1** any time for
shortcuts and the current version.

**Rooms.** The main chat is for everyday questions. Anything you want
to pick back up later belongs in a **room** — a name, a folder, and
its own thread. `/room physics` takes you in, `/leave` takes you out,
and the last room you were in reopens the next time you launch her.
More in [rooms.md](docs/rooms.md).

**Roles.** There are two modes: `/role fast` and `/role research`.
File and git work always stays on Fast. Once setup is done, both modes
actually use the same model (`qwen3.5:9b`, unless you picked something
else) — Research just means a longer reasoning loop, not a bigger
model. See [models.md](docs/models.md).

**Phone.** One sideloaded **Arelis** app, paired by scanning the QR
code in Settings → Notify. Google Messages stays your everyday
messenger — she sends texts from your SIM only after you approve the
card. If the PC is off, the phone keeps its own conversation going; if
you installed Gemma during pairing (~2.6 GB), she can keep talking
on-device, and those messages sync back once the PC is up again.

**Her browser.** Not your everyday Chrome — her own separate window
that you can watch. She'll never type a password or click Book, Pay,
or Checkout. See [browser-control.md](docs/browser-control.md).

**Voice.** Say **Hey Arelis** — just her name on its own won't wake
her. Ctrl+Shift+M starts a conversation, Ctrl+M is for dictation.
Details in [voice-wake.md](docs/voice-wake.md).

**Jobs.** Found under the calendar tile (Ctrl+7). Set a prompt and a
time, and she'll email you the answer. Requires mail to be set up —
see [jobs.md](docs/jobs.md).

**Memory.** Managed under Settings → Memory. Dated backups are kept in
`data\backups\` for two weeks.

## What she can actually do

Work inside rooms and folders you've approved. Search the web and read
real pages. Drive her own browser. Track facts, goals, and tasks. Read
text out of images (OCR), look at pictures, and resize images on disk.
Generate images if you've got ComfyUI set up (it doesn't start
automatically). Listen and speak. Run scheduled jobs that email you a
digest. Handle closed-form math, unit conversions, short Python
snippets, charts, and documents.

Mail, calendar, and texting through your Android phone all work once
you've connected them. She can also produce a PDF, Word document,
spreadsheet, or markdown note for you.

If you're running from a source checkout, you additionally get the 3D
solar system and Earth view inside Reality
([earth.md](docs/earth.md)). Installed copies still get Reality as a
room — chat, CAS, and Horizons all work — but the 3D visuals
themselves don't ship in the installer.

There's test coverage for most of this, but voice timing, a real
handset, and image generation have really only been exercised
end-to-end on the author's own hardware — so if something behaves
oddly on yours, it's worth opening an issue. Again, the current
published installer is **0.2.4**; see
[whats-new.md](docs/whats-new.md) for what's changed.

## Further reading

| Document | What's in it |
|---|---|
| [whats-new.md](docs/whats-new.md) | 0.2.4, and what's in this checkout |
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

See [CONTRIBUTING.md](CONTRIBUTING.md). Found a security hole? Please
report it privately per [SECURITY.md](SECURITY.md) rather than opening
a public issue.

Nothing that identifies a real person should ever go into this
repository — there's a test that enforces it.

## License

[GNU Affero General Public License, version 3 or later](LICENSE).

You're free to use it, read it, change it, and share it. If you share
a modified version — including by running it as a service other people
connect to — you need to make your changes available under the same
license.
