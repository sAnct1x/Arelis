# Desktop

Arelis can drive **your Windows session** — open apps, switch
windows, type, click. That is not her Chrome. Web stays
[browser-control.md](browser-control.md).

You watch it. Stop / Pause / Go on the Drive strip (or out loud)
work the same as a browser drive.

## Tool

`desktop` actions: `open`, `windows`, `monitors`, `focus`, `snapshot`,
`read`, `click`, `type`, `press`, `hotkey`, `scroll`, `screenshot`,
`wait`.

- `open(target=notepad)` launches or focuses. Aliases: notepad,
  calculator, explorer, paint, snipping tool. Start Menu titles
  work too. A raw `.exe` path is refused.
- `windows` lists visible titles. `focus` brings one forward.
- `monitors` lists displays (`1|primary|3840x2160|left`).
- `screenshot` without a target is the primary monitor. `target=left`
  / `right` / `2` / `top` picks a display. `target=Kindle` (a window
  title) or `the book` (Kindle / Acrobat) grabs that window — not the
  whole desk. The grab already reads the text (tiled on a huge page
  when they named a problem / paragraph). `vision` only for a
  diagram. She does not highlight in the other app. A follow-up
  ("now the third paragraph", "how do I solve this") grabs again;
  the still is deleted unless you said save/keep. "What's on the
  screen" is a monitor. "What's on this page / tab" is her Chrome.
  If a tiny problem number cannot be resolved, she says so — she
  does not invent it. Protected / overlay / fullscreen grabs fail
  out loud. The window is captured from the monitor Windows says
  it is on (not always the primary).
- `snapshot` ranks named controls in the focused window (`[d1]`…).
  Needs the desktop extra (`pip install -e ".[desktop]"`).
- `click(text="7")` or `click(ref=d3)`. `x,y` only after
  `screenshot` then `vision` this turn. The PNG is a look still —
  deleted after she reads it, unless you asked to save it.
- `type` into the focused field. Password / PIN / OTP are refused.
- Checkout / Pay / Empty Recycle Bin / Uninstall / Format stop.
  UAC Yes is refused.

## Sanctuary

Launch is an allow-resolver, not "run any path."

Never started: `cmd`, PowerShell, `regedit`, `diskpart`, `format`,
`taskmgr`, anything that wants Administrator.

Never opened as files: `C:\Windows`, other users under `C:\Users`,
`data/secrets.yaml`.

`notepad.exe` lives in System32. That folder is not the ban — the
job is.

Unattended jobs do not get this tool.

## Confirm

`agent.confirm_desktop` (default true) pauses when she offers the
desk. An ask you already typed or said is the grant. Deletes, Pay,
and UAC still pause. Settings: "the desk, when she offers it."
