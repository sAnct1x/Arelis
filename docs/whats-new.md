# What's new

The installer on GitHub is **0.2.2**. This file is sitting on top of
that. Restart **Arelis (dev)** to feel checkout work that has not been
tagged yet.

Published: [v0.2.2](releases/v0.2.2.md).
Not tagged yet: [v0.2.3](releases/v0.2.3.md) — first open names a model.
Older: [v0.2.1](releases/v0.2.1.md).

## In this checkout (not tagged)

- **Rooms come back.** The last room you actually entered is there on
  the next launch. Leave if you want orbit instead. Creating a room
  without going in does not count. Jobs never resume a room.
- **Mail, SMS, and calendar stay dark** until they are connected. They
  are hidden from Systems. Chat will say she cannot, instead of calling
  a tool that always fails.
- **A clock ask does not load every tool.** "What time is it" used to
  pull the full schema list (~11k prompt tokens) and plan a web search.
- **Typing in the window** no longer raises a `TypeError` on every
  keystroke.
- **Documents.** Ask her to make a PDF, a Word file, a spreadsheet, or a
  markdown note. She writes a real file — click **open** or **show in
  folder**. In a room it lands in that room's `documents` folder. In
  orbit it lands under `outputs/documents/`. Chat is not the document.
- **Charts.** Same open / show chip as documents. In a room the PNG
  lands in that room's `plots` folder. In orbit it lands under
  `outputs/plots/`.
- **Mail.** She can trash, archive, mark read/unread, move, and make a
  folder — Allow first. Looking still does not mark mail read. Jobs
  cannot change the mailbox. Delivered mail cannot be rewritten.
- **Calendar tile.** Ctrl+7 still opens the local calendar. Chat will not
  pretend Google is connected until you connect it.
- **First open can name a model.** This checkout asks after the folder
  question. The published 0.2.2 installer still only asks which folder.
