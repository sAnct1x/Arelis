# What's new

The installer on GitHub is **0.2.3**.

Published: [v0.2.3](releases/v0.2.3.md).
Older: [v0.2.2](releases/v0.2.2.md). [v0.2.1](releases/v0.2.1.md).

## This checkout

Notes for the tree you have now. The 0.2.3 notes below are what that
installer shipped. A few of them are no longer how this tree behaves.

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

**Glass.** One lowercase voice. Thinking is the essay — no `think` /
`model` / `tool` prefixes — with housekeeping as a footer.
Workspace is file names, one chrome row, `..` to go up. Settings
tabs are `audio` / `window` / `allow` / `notify` / `roots` /
`memory`. Idle readout is `ollama` / `listening`, not caps. After
the last finished answer: `copy` · `again`. Tables in an answer
are columns, not orange cages. An empty history title is **new
chat**; the lamp follows the click; dates say today / yesterday.
Hue stays sodium (`#ff7a22`). Icons stay unlabeled.

**Jobs.** Timed prompts email a digest. Calendar tile → **jobs**. Needs
mail. Already in the installer; the page is new. [jobs.md](jobs.md).

**Reality.** The permanent room (slash id `physics`). Source checkout
only for the plate: Ctrl+8 / View → Reality, true-scale solar
(`.[astro]`) and hands (`.[spatial]`). Not in the installer. Reality
cannot be forgotten. Travel to Earth (or say enter Earth) lights the
Earth zone — an observer of whatever is broadcasting or published.
Earth is a zone, not a second room.

Now: `arelis/earth/feeds.py` is **108 shipped / 25 keyed / 3 later / 4 out**.
Live is distance-gated (`arelis/earth/lod.py`): from space only
satellites are fetched; closer in, local planes; closer still, boats
and planes and no satellite refresh; at city scale every toggled
layer, still boxed to the look area so we do not hammer every 511
from orbit. Earth layer chips start off except satellites and ISS; the bar
only lists what the current band can show. Click a country or city
to fall toward it. Enter Earth jumps the clock to now and opens the
Cesium globe (WebEngine, astro extra) for the planet only — Arelis
keeps the starfield and the sodium HUD. NASA GIBS is the ground if no
Google key is pasted; Photorealistic 3D cities light up close-in when
`earth.google_maps_key` is set. Natural Earth country lines paint on
the Qt disc so landfall still reads if Cesium is down. The GL Earth
map shares that frame — Greenwich is the texture center, not the seam.
The Earth
software sphere can grow once you have fallen in so the NASA albedo
still reads; optional `earth_8192.jpg` (Blue Marble shallow topo) is
preferred when present; optional Streets (OSM) go to z15 at city band;
optional building footprints are a city-band chip, look-pin boxed,
and the same outlines ride Cesium when WebEngine is up.
Viewsheds say No terrain. Collision stays no mesh, no DEM. OpenSky uses a bbox
(1 credit) once you have a look box. Reality telemetry is on while
we tune: `logs/reality.log` + `logs/reality.jsonl`
(`arelis/physics/telemetry.py`). Stream URLs never land there.

Earth grew another worldwide catalog batch: ALGO and DelDOT cameras
with official look-from, NZTA and Quebec 511 camera pins, Quebec
events, Autobahn roadworks, and no-key WZDx for NC / IN / KS / WA /
NB / PE / YT / AK / NV. Keyed adapters are wired and wait on paste:
WSDOT cameras + alerts, OHGO, DriveNC cameras, NSW cameras,
DriveTexas conditions, and the Travel-IQ CARS fleet. Same-host
completeness pass added South Australia closures, Main Roads WA
roadworks + events, INGV / GEOFON / IRIS / NRCAN / GeoNet station
text, MoDOT cameras, Quebec construction and road conditions, and
Fintraffic / Lithuania / Quebec road-weather stations. Individual
cars stay a labeled hole.
Live merge runs adapters in parallel. Air and ships coast as
dead-reckoned, then stale. Each Earth layer and solar body kind has
its own sodium mark (`arelis/ui/earth_marks.py`) — Qt overlay, Cesium
billboards, inspect card, and solar roster share the same drawn paths.
Heading is the nose of the air/sea mark. A photoreal miss does not
kill the globe. Overlay paints freshness and an inspect card with
source. Completeness is the anti-beacon —
do not thin a region. Mid-ocean VHF is deaf; we do not buy sat-AIS.
Starlink is a sample, not a painted shell. Individual cars stay a
labeled hole. WGS84 on `earth.local_camera` is enough for an owned pin.
Click an owned camera for live footage (the stream you pasted), sitting
in the frustum when heading is set. Official publisher stills refresh
on click when the catalog JSON includes them. Stream URLs stay off the
pin. The lab camera uses ecliptic north as up.

Next: more no-key 511 / WZDx / camera inventories and official still
CDNs (WA/TX cameras stay keyed); VIIRS only if Mines opens FINAL without a
login. Out stays out (sat-AIS, unowned cameras, face index, VIN).
[earth.md](earth.md).

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
