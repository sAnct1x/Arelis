# What's new

The installer on GitHub is **0.2.3**.

Published: [v0.2.3](releases/v0.2.3.md).
Older: [v0.2.2](releases/v0.2.2.md). [v0.2.1](releases/v0.2.1.md).

## This checkout

Living notes for the tree you have now. The 0.2.3 notes below are what
that installer shipped. A few of them are no longer how this tree
behaves.

**Turns.** The full tool schema array rides every turn so Ollama can
reuse the prefix. A greeting that skipped schemas (the 0.2.3 clock-ask
shortcut) blew that cache and made the next real question pay ~40s of
prefill. Tiny asks (clock, hello, thanks, "who are you") still stream;
tool-bearing turns still hold the answer until the tools finish. "Who
is this" is not identity.

**First message.** Launch pins the model, then seeds that prefix. The
window says **loading the model…**, not **thinking…**, until the seed
is done.

**Voice.** Conversation and dictate are Sherpa-ONNX (Kroko Zipformer).
Speech out is Kokoro-82M `af_heart` on CPU (Piper fallback). End of
turn is Silero plus Smart Turn v3 when the ONNX is present. Headset
barge-in is the next question. [voice-wake.md](voice-wake.md). First
run may download those weights; they are not stuffed in the setup
`.exe`.

**Jobs.** Timed prompts email a digest. Calendar tile → **jobs**. Needs
mail. Already in the installer; the page is new. [jobs.md](jobs.md).

**World.** Source checkout only. Physics room, Ctrl+8, solar lab
(`.[astro]`) and hands (`.[spatial]`). Not in the installer. Physics
cannot be forgotten. Travel to Earth (or say enter Earth) lights the
Earth zone — an observer of whatever is broadcasting or published.
Not a product title.

Now: `arelis/earth/feeds.py` is **63 shipped / 9 keyed / 3 later / 4 out**.
Live merge runs adapters in parallel. Air and ships coast as
dead-reckoned, then stale. Overlay paints freshness, heading ticks,
and an inspect card with source. Completeness is the anti-beacon —
do not thin a region. Mid-ocean VHF is deaf; we do not buy sat-AIS.
Starlink is a sample, not a painted shell. Individual cars stay a
labeled hole. WGS84 on `earth.local_camera` is enough for an owned pin.
The lab camera uses ecliptic north as up.

Next: more no-key 511 / WZDx / camera inventories; OpenAQ after a
paste; VIIRS only if Mines opens FINAL without a login. Out stays
out (sat-AIS, unowned cameras, face index, VIN). [earth.md](earth.md).

**Mail.** There is no Mail tab. Credentials live in `data/secrets.yaml`.

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
- **A clock ask skipped the tool list** in that installer. This checkout
  keeps the schemas on (prefix cache) and skips the web floor instead.
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
