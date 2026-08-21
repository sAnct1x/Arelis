# What's new

The installer on GitHub is **0.2.3**.

Published: [v0.2.3](releases/v0.2.3.md).
Older: [v0.2.2](releases/v0.2.2.md). [v0.2.1](releases/v0.2.1.md).

## 0.2.3

- **First open names a model.** After the folder question she looks at
  this PC, recommends one tag, and pulls it. Confirm it, or pick Gemma /
  DeepSeek. One model at a time — both chips are that tag. An upgrade
  from 0.2.2 that never pinned a tag is asked once.
- **Rooms come back.** The last room you actually entered is there on
  the next launch. Leave if you want orbit instead. Creating a room
  without going in does not count. Jobs never resume a room.
- **Mail, SMS, and calendar stay dark** until they are connected. They
  are hidden from Systems. Chat will say she cannot, instead of calling
  a tool that always fails.
- **A clock ask does not load every tool.**
- **Typing in the window** no longer raises a `TypeError` on every
  keystroke.
- **Documents.** PDF, Word, spreadsheet, or a markdown note — a real
  file. Open / show in folder. In a room: that room's `documents`
  folder. In orbit: `outputs/documents/`. Chat is not the document.
- **Charts.** Same open / show chip. Room `plots` folder, or
  `outputs/plots/` in orbit.
- **Mail.** Trash, archive, mark read/unread, move, make a folder —
  Allow first. Looking still does not mark mail read. Jobs cannot change
  the mailbox.
- **Calendar tile.** Ctrl+7 still opens the local calendar. Chat will not
  pretend Google is connected until you connect it.
- **Phone.** One sideloaded app. Scan the QR on the same Wi-Fi. Same
  conversation as the desktop. If the PC is away, Gemma on the phone
  (install after pair, ~2.6 GB). Those words copy in when the house is
  back.
