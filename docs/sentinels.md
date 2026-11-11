# Sentinels window

Arelis starts Sentinel in the background when she launches. The Sentinels
window lets you watch the swarm live: the 3D view, the roster by caste,
the mission picker, and the searchable log console.

Snapshot polling and HUD command requests run off the GUI thread. A slow
or unavailable bridge cannot block window input; duplicate polls do not
accumulate. Command status remains pending until the backend answers.
The side panels shrink on smaller windows, leaving room for the scene.
Focus uses a wider camera distance so the unit body remains visible.

## Opening it

View menu, then **Sentinels**. In Filament the same item is in the field
menu. A small mote below the orbit opens it too. The window sits as an
inset over the main plate (no OS frame) and leaves a strip on the right
uncovered. It takes its colours from the theme you are using (Night,
Sodium, or Filament). While it is open, Arelis and the orbit tree fade
to about 20 percent. Closing it, quitting Arelis, or an error that
cannot show the page restores them. Esc or the close mote on the inset
closes it. The close mote is drawn inside the 3D scene, top right; Tab reaches
it and Enter or Space presses it.
Closing the window saves the scene's compiled shaders to
`sentinel/overseer/pipeline.cache` in the Arelis data folder, so the next start
opens it without compiling them again. A file from another Qt version or graphics
backend is ignored and replaced.

The view is a Qt Quick 3D Overseer. Live units from the hive snapshot
are drawn as instanced Iris LOD meshes (about 12k / 4k / 1k triangles
per unit), one model per caste, LOD, and part, with caste colour and
claw opening on each instance. If a hundred units would go over the
300k triangle ceiling, farther units drop to a coarser LOD or are
culled. Tentacle motion is a vertex wave on the hull and the glow, driven
by each unit's phase plus a time uniform, not CPU skinning. Animation
speed comes from real unit activity in the snapshot (slow idle sway while
patrolling, faster curl and reach while working or engaged, nearly still
under EMP), packed into the instance custom data so the GPU keeps 60 fps
without per-tentacle QML objects. While a unit has open fetch requests
(a harvest target in the snapshot that has not come back yet), one pair of
its front tentacles per request, up to three pairs, swings forward toward
the target it faces and settles there in about 0.4 s. The other tentacles
curl, loosely while the unit is idle and tighter while it is busy. The
vertex shader does this from each instance's data, so there is no extra
work per frame on the CPU. Four fixed source
nodes sit at the scene edge (arXiv, Wikipedia, Horizons, Web). A source
lights up and beams toward the core only while a real harvest fetch for
that source is live in the hive snapshot (a harvest_target node or a
harvester unit mid-extract). Idle sources stay dim. Each source has a
readable name under it, the same size lit or idle, with "fetching" or
"idle" below; a source hidden behind a HUD panel hides its name too.
No extra poll timer: the existing snapshot path carries the signal. When a harvest result
comes back, its real title and web address fly from that source to the
core as two lines of glowing text. The letters keep moving along the arc
and dive into the core one after another, and the line is gone within
about five seconds.
The text comes only from the result's receipt in the hive snapshot; a
result with no title shows no text. At most four results fly at once
(a fifth ends the oldest), each line is cut at 60 characters, and text
from every source is the same size. The GPU moves the letters, so the
CPU only builds them once when a result arrives. Idle units (patrolling
or docked) fly around the core on tilted bands, one band per caste:
Sanitizers closest, then Wardens with Stalkers, then Harvesters. Each band
has its own tilt and height and splits into two to four side-by-side lanes
as its caste grows (one more lane per twelve units), and the bands widen
with more units. Inner lanes go round a little faster. Tripwires ride a
ring at the outer edge, and the sources sit just past it. Units that are
working keep the position the hive reports. Where a unit sits on its lane
follows the snapshot clock, so the view needs no extra timer and draws all
lanes as one line set plus the edge ring. The Overseer shows up to 128
units. The glow
writes clip position from that waved mesh; the lens writes clip
position from the mesh as modeled, so those unshaded parts stay on
the units instead of stretching into a covering plate or stray streaks. The wheel,
trackpad, and + / - keys dolly the camera between the default view and
6 m, with the approved rubber band at the near end. Each time the window opens, the camera
starts on the default view: the wide, low frame from the design (about
31.7 degrees down, 95 m or more from a point just in front of the hive)
pulled back only as far as the window needs so the whole edge ring, the
outer band lanes, and all four edge sources with their names sit clear of
the top bar, Swarm list, inspector, and console. A small window (such as
1028 x 749) shows the same frame from farther away. The first three wheel
notches ease out of the default view: each one tilts the camera by the same
step (about 7.8 degrees) and closes the distance evenly, so the third
notch lands on the 55 degree, 96 m wide mark of the zoom curve below.
Scrolling back out retraces those steps and stops on the default view.
Opening the window follows the entry
timing (mote, edge, fill, reveal, then panels); closing reverses it.
Reduced motion uses a short crossfade. A native HUD sits on the view:
a status strip across the top (Threats, Defenders, Units by caste,
Warrants, Last event; see "The status strip" below, and what the
colours and Warrants mean:
[sentinel-overseer-colours.md](sentinel-overseer-colours.md)), a grouped Swarm list (search, group by
caste, task or ring, 44 px rows, engaged first), a docked inspector for
the selected unit (see "The inspector dock" below), and a forensic
console for live logs and mission dispatch. Inspector actions and
dispatch use the hive's existing command paths. Dispatch needs a query
(a topic, or a Horizons target) unless Mode is security_audit; if the hive
refuses a request the console says why, for example "Refused: Enter a
research topic or Horizons target." Dispatch, the query field and each
Mode choice have names for screen readers and UI Automation. The Mode box
also lists each mode as its own item (multi, arxiv, horizons, wikipedia,
security_audit) without opening the menu, so a screen reader or UI
Automation can pick one directly. Recall is disabled:
it would shrink the whole caste, not just this unit. Focus frames the
selected unit from its snapshot position (local camera only; no new hive
route). Retask is disabled: the hive cannot give one unit a new job, and
if this unit is gone a retask could pick a different one. Retire posts
retire_unit for that unit after an in-place confirm. Emergency stop
posts the existing halt and cannot restore it from this HUD. Each swarm
row has an accessible name and can be invoked to select that unit; the
inspector stays on the selected unit across live snapshot updates. The
swarm footer has Deploy (existing caste scale-up) and Recall, which
stays disabled. Mission mode and other combo boxes use the dark
Filament control fill, text, and popup. Disabled inspector actions
(Recall and Retask) drop "(unavailable)" from the label, show a short
tooltip, and stay refused by the host. Focus is enabled when a unit is
selected. The swarm list uses a standard
vertical scroll bar so later groups stay reachable by scrolling while
other headers stay expanded; collapsing other groups is not required to
reach them. The bar's thumb is Filament violet (`#8b6cf2`) on a dark
track (`#1c1430`), not a light system control. The current caste header
stays pinned at the top of the list while you scroll through that group. The Swarm list, inspector, console, and top bar use the designed
Filament panel fill `#0e0920` at full opacity so the 3D scene stays
behind those plates instead of drawing through list rows or the
inspector. Unselected rows use that same fill (selected rows stay
`#2a1a4a`). Selecting a unit aims the camera at that unit's snapshot position
(not the hive). Wheel and trackpad dolly along the view axis at 35 mm
with a factor of 1.18 per notch past the 96 m wide mark, rubber-banded
8 percent past the 6 m limit. Pitch follows the approved marks: 22 degrees across 6 to
9 m, 36 degrees at 32 m, and 55 degrees at 96 m. Focus
dollies to 7 m (inside the 6 to 9 m close band) on the selected unit.
Fit swarm sets camera mode to fit and returns to the default view described above (local, no backend POST), so the whole hive and every source label are on screen again. While the mode is fit, live snapshot refreshes and inspector selection changes do not move the camera target back onto the selected unit; Focus sets camera mode to follow and frames that unit again. The inspector stays on the selected unit either way. A wheel hit-point, when set, keeps that
world point fixed (new target = P + (target - P) * (d_new / d_old)).
A lens shift centres the swarm in the panel-free viewport.
The camera near clipping plane is explicitly 1 m (Qt defaults to 10 m,
which clips the subject at the approved 6 to 9 m close distances). This is
not a dolly limit: Focus remains 7 m / 22 degrees with a 35 degree FOV;
the far clipping plane stays at Qt's 10000 m default. At the nearest 6 m
camera position, the 1 m plane leaves 5 m toward the camera from the
selected origin. This gives room for the body and close appendages without
requiring the complete heading-dependent LOD0 tail AABB (about 8.8 m long)
to fit at every orientation. It is a geometric clipping policy, not a
per-frame artifact clamp or a shift to the mesh pivot. Remeasure the
painted subject after clipping is corrected; a centered 60 percent close
portrait and actual-machine validation are not implied by this setting.

Babbage and other reports must read the live QML values
`cameraDistance`, `cameraPitch`, `cameraTargetX`, `cameraTargetY`,
`cameraTargetZ`, `selectedUnitId`, `framing`, and `cameraMode` from the named
readonly texts `OverseerCameraDistance`, `OverseerCameraPitch`,
`OverseerCameraTargetX`, `OverseerCameraTargetY`, `OverseerCameraTargetZ`,
`OverseerCameraSelectedUnitId`, `OverseerCameraFraming`,
`OverseerCameraMode`, and the combined
`OverseerCameraEvidence` line (`cameraDistance=… cameraPitch=…` and the
other live keys). The same-frame instance dump is the named
`OverseerFrameDump` line and `frameDump()` (`frameId`, `selectedId`,
`selectedCaste`, `modelKey`, instance position and colour after the
instance write, remembered position, camera position and target, FOV,
aspect, lens shift, and `mapFrom3DScene` projections when Qt exposes
them). Do not treat a later HTTP `unit_view_pos` sample as the same
instant as that dump. The host `camera_report()` object and `cameraEvidence()`
match the camera keys. The Sentinels host logger writes the same keys after
Focus or Fit swarm (`overseer cameraDistance=…`). If the scene is down
those fields are absent — do not fill them with defaults. Name a still
from those live values: `overseer_closezoom_*` only when distance is 6 to
9 m, mid near 32 m, wide near 96 m. Nondestructive test inputs:
`selectUnit`, `focusSelectedUnit`, `applyWheel`, `setWheelPivot`,
`fitSwarm`, and the accessible `OverseerAction_fitSwarm` control
(Accessible name `Fit swarm`, local, no POST; invoke the press action or
click). Do not invoke Deploy, Retire, EMP, Recall, or Retask to move the
camera. Cursor-pick on the rail is not claimed complete.

theme.id (sodium metadata vs Filament pixels) and leftover hive-specular
clips on settled stills are separate appearance work, not claimed fixed
by this camera batch. Visual review, load, and frame timing on a real
machine have not been accepted yet.

### The status strip

Under the Sentinels title, a green dot reads "hive live · all local ·
sending out blocked". To its right, five blocks give the hive at a glance.
They are read only: nothing highlights when you point at them, and only
Last event responds to a click.

- **Threats**: the threat count from the hive. 0 reads "All clear" in
  green; any threats read in rose with a rose outline. If the hive does
  not report it, it reads "?" and "Not reported". Hover it to see which
  castes are engaged.
- **Defenders**: how many Wardens there are, and how many are engaged
  (the same number as the Warden header's active count in the Swarm list).
- **Units by caste**: the total, then Warden, Stalker, Harvester,
  Sanitizer and Tripwire, always in that order. A caste with no units
  still shows, dimmed, with 0.
- **Warrants**: evidence receipts in memory. Hover it to read
  "Evidence receipts in memory (includes up to 120 from earlier runs)".
- **Last event**: the time and a short summary of the newest event in the
  console. Click it to scroll the console to that row (or to the newest
  row if the current filter hides it).

On a window too narrow for all five full blocks (the 1200 px default
included), Threats and Defenders stay as they are and the other three
become compact chips: a small icon and the value (units total, warrant
count, time of the last event). Hover a chip for its full label and
detail; the Last event chip still scrolls the console when clicked. The
header stays the same height. On a very narrow window, chips that still
do not fit drop from the right so none is cut off.

The strip updates with each snapshot, not every frame.

### The event log

The console at the bottom lists the hive's events, newest first, one line
each: the time, a ×N badge when the line repeats, the unit (in its caste
colour), the message in plain words, and for repeats the first to last
time on the right.

- **Repeats collapse.** The same event from the same unit shows once with
  a count. A pack's start and its successful finish merge into one line,
  such as "Tripwire pack of 3 ran verify, all ok". A pack that has started
  but not finished shows as its own "running" line. A failed run is never
  merged: it gets its own line with a rose dot and the reason, such as
  "failed: timeout". So a one-off event (a new port, say) is not buried
  under hundreds of routine patrols.
- **Counts cover the whole time the window is open**, not just the last
  60 events the hive sends each time.
- **Repeats ×N** is on by default and collapses repeats. Turn it off to
  see every line again, newest first.
- **Plain words.** Debug text such as "ok=True, title=" is gone, and
  "3-Sentinel HUNTER-SEEKER Pack (...)" reads "Tripwire pack of 3". Hover a
  line to see the raw log line exactly as the hive wrote it.
- **No cut-off line.** The log always shows a whole number of lines with
  space below the last one, at any window size.

### The inspector dock

When you select a unit, a 360 px panel docks on the right, 24 px from the
window edge, sized to its content. It never floats over the swarm: the
camera recentres on the free well that excludes the dock column. With
nothing selected the dock is gone; there is no empty "Select a unit"
panel.

- **Header**: caste colour dot, the unit id, a deselect control, the
  caste and role line (for example "Harvester · Gather"), and a state
  chip.
- **LIVE**: only fields the hive reported (state, tentacles, target and
  so on). Anything else is listed once in a dashed box that reads "Not
  reported by the hive yet", never as seven "unavailable" rows.
- **CAPABILITIES**: the caste's allowed tools as chips.
- **ACTIONS**: Focus (reads Focused while focused), Fit swarm, Retask,
  Recall and Retire in a two-column grid. Retask and Recall stay
  disabled with a tooltip. Retire is rose-outlined and asks you to
  confirm in place for four seconds.
- **RECENT EVENTS**: the newest three console lines for that unit, or
  "None from this unit this session."

## When Sentinel is offline

If Sentinel is not running the window says **Sentinel offline** and shows
a **Start** button. Start runs the same start Arelis uses at launch. The
page appears once Sentinel is up, usually within a few seconds.

## Privacy

The page is served on `127.0.0.1` only. The session key that lets the page
talk to Sentinel travels in the part of the address after `#`, which is
never sent to the server or written to its logs, and the page removes it
from its history as soon as it loads.

## Asking Arelis about the swarm

Arelis can read the swarm for you and, when you ask, command it. She can
never undo an emergency stop: only you can, from the Overseer.

- "How is the sentinel swarm doing?" She reports whether the emergency
  stop is on and how many units each caste has.
- "List the warden sentinels" or "which sentinels are patrolling?" She
  lists units, filtered by caste, state, or words in their current task.
- "Show recent sentinel threat logs." She reads the event log with the
  same filters as the Overseer console: all, threats, injection
  (sanitize), harvests, and tripwire, plus a text search.
- "What sentinel castes are there?" She lists built-in and custom castes
  with what each one is allowed to do.

If Sentinel is not running she says so instead of guessing.

## Asking Arelis to command the swarm

- "Deploy three more wardens." She adds up to 50 units of a known caste at
  a time; the swarm's own unit limit still applies.
- "Stand down the harvesters" or "retire unit SNT-WRD-002." She retires one
  unit or a whole caste. "Stand down those 3 harvesters" retires exactly 3
  and leaves the rest; she tells you how many she retired and how many remain.
- "Have the wardens scan sockets." She gives a caste one task it really
  supports: harvesters fetch a page or search arXiv, Horizons or Wikipedia;
  wardens scan sockets, check a URL or intercept; tripwires watch a folder or
  verify; sanitizers clean text or HTML or inspect an archive; stalkers list
  local processes, inspect one pid, run a heuristic rogue check, or read host
  RAM use. Anything else is refused. Sentinels still cannot send your data out.
- "Research exoplanet transits with the sentinels." Harvesters search arXiv
  and Wikipedia. She tells you the mission started, not that it finished;
  its result, or why it failed, shows in the log. At most four research
  missions run at once, each with at most eight targets; further requests
  wait until one finishes. Older finished mission records are dropped after
  a while, or when there are too many, but a mission that is still running
  is kept.
- "Emergency stop the sentinels." Every unit halts at once, with no card to
  click first. Only you can lift it.

Deploy, stop, retask and research ask first in the usual way unless your
own request already asked for them.

## Stalker host process audit

Stalker is a built-in caste that audits processes on this machine: the process
tree around a pid, the owning executable, and remote endpoints of that
process's local connections. It is a local read, not proven cyber-swarm
defense and not Arelis deciding on her own. Findings from the rogue check
are heuristics (known names, encoded command markers, Office spawning a
script engine, or an executable from a temp folder). They can be wrong.
It does not kill, quarantine, or ban a process, and it does not dump
process memory: the memory check is host RAM totals and process percents.
Command lines are not returned, so secrets in arguments stay off the report.
If a process has disappeared or the OS denies access, the report says so,
and a partial inspect lists the fields that failed. If a list, rogue check,
or inspect hits its count cap (including two heuristic hits on one process),
the report sets truncated rather than pretending it is complete or calling
the miss an unknown error.

List, rogue, and RAM walks check a 1.5 second cooperative budget between
process records. That is not a hard deadline on a single OS or psutil call,
and inspecting one pid has no time budget. Cancelling a retask does not stop
a worker already inside those calls, and this slice does not add a new lock
against overlapping cancelled retasks. Payload allowlists constrain keys
only; limit and threshold values are clamped by the handler.

Deploy a stalker and retask those capabilities the same way as the other
castes. Recent work still shows in the event log; search for stalker or
PROCESS rather than a separate hunt filter.

## Custom castes (backend only)

The hive can register a custom caste whose capabilities are a subset of the
built-in tools, with exactly one purpose string, and keep that definition in
the runtime data directory across a restart. Built-in names cannot be reused
or deleted. Arelis does not yet have model tools to build or remove a caste;
those remain a proposal, not something she can call. This does not grant
new privileges, run rule expressions, or claim that a purpose string is
checked by a language model: one purpose field is enforced as a single
plain-text value of bounded length.

## What the swarm does on its own

While Sentinel is running it watches this machine on a timer: open sockets,
new listening ports, busy remote peers, file-baseline changes, and canary
files. Each distinct signal has its own short cooldown. If the hive still
has room to remember that signal, it may ask an idle warden to scan sockets
or an idle tripwire to verify files. A host scan and that retask do not run
at the same time, because the retask uses the same scanners. That is the
hive following fixed rules, not Arelis deciding, and it does not prove the
machine is protected.

It does not install a firewall rule, kill a process, or repair files on its
own. A "listed" peer in the Overseer is a record in Sentinel's own list, not
an operating-system block. A single change on a watched folder can raise a
file alert even when you made the change. The emergency stop still halts new
work at once; only you can lift it. After you lift it, host watching starts
again.

See [The Overseer and the main window](sentinel-overseer-window.md) for how the Overseer draws next to the main window.
