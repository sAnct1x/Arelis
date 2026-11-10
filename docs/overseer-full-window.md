# Overseer: full window, chat off

When you open the Overseer (View menu, then **Sentinels**), the swarm gets
the whole Sentinels window and chat turns off until you close it.

## Full window

The 3D scene runs edge to edge. There is no side panel and no boxed
header: **Sentinels** and one summary line sit as text over the sky. The
summary line reads, in order: units, how many are fetching, threats,
Wardens patrolling and engaged, warrants, the last event, and the hive's
health ("hive live · all local · sending out blocked"). On a narrow window
the line drops pieces from the right; hover it, or ask a screen reader, for
the whole line. Hover **warrants** for what that number counts. Every
control from before is still there; the list and the event log just fold
away until you want them. Panels keep a small margin (2 percent of the
window) from the edges.

Opening or closing a drawer never moves the camera or resizes the scene.

## Glow

Only the brightest things in the scene glow: unit eyes, the source cores
and fetch beams, and (when they go over the threshold) tool beads. The
orb's soft core stays under the glow threshold. Hulls, lanes and the
perimeter never glow. The glow is a soft halo a few pixels wide around
each eye. Edges are not smoothed (antialiasing is off), which keeps the
Overseer within its frame budget.

## The orb, units and sources

The core is a lavender glass shell with a soft nucleus and quiet drifting
filaments. Three rings around it are real state, not decoration:
**Memory · N from last chat** is how many memories were still in context
when the Overseer opened, **Tools N running** lights one bead per tool
that is actually running, and harvest result titles sit on the outer
orbit when there is room. The orb's brightness follows the model's real
speed (it sits at its idle glow when no tokens are flowing). Labels stay
outside the shell disc.

Click the orb, or the **Core** button in the header next to Emergency
stop, to frame the orb itself (about 15 m at a typical full window, 22
deg pitch). Unit bodies hide while you are in that view, and the lanes
dim. Esc, or wheeling out past 24 m, returns you to the normal overview
ease. The 24 m unit Focus and the default overview scale are unchanged.
Wheeling inside the core view stays between 10 m and 24 m.

Each unit is a plated body with three glowing eyes at the wide view, and
short solid tentacles instead of the old hairline threads. A unit that is
fetching, focused, or close enough steps up to a more detailed body with
linked tentacles; the closest close-up uses the full armour model.

The edge sources are glass nodes with a thin halo. The label under
each one is the source name and how many requests are open there, or
"idle" when none are.

## Chat is off while the Overseer is open

While the Overseer is open:

- The chat composer is disabled, so nothing you type starts a reply.
  Again and camera captures do not start a turn either.
- Voice stops listening, including "Hey Arelis".
- A reply that was still running is stopped.
- In Filament, the chat tile is hidden.

Close the Overseer (the x mote top right, or Esc) and chat comes back as
you left it: the composer works again, the chat tile returns if it was
open, and "Hey Arelis" listens again if it was on before. Texts (SMS) and
scheduled jobs are not affected.

To give Arelis a job while the Overseer is open, use the Dispatch bar.

## The Units drawer

**Units** (small text, top left) opens the unit list as a drawer over the
left of the scene. It is closed each time you open the Overseer. Inside it
you can search units, group them by caste, task, or ring, select a unit,
and use Deploy. Press **Units** again to close it. Selecting a unit opens
the inspector on the right, as before.

## The Dispatch bar

The bar at the bottom centre, just above the replay strip, works like the
chat composer: pick a mode (multi, arXiv, Horizons, Wikipedia, security
audit), type the query, then press Enter or **Dispatch**. The result of the
request shows just under the bar. When you select a unit working on a job
you sent this way, the inspector ends with "task from Dispatch at" and the
time you sent it. This covers jobs sent while the Overseer is open.

**Events** (bottom right) opens the event log above the bar, with the same
filters, search, and Repeats toggle as before. Clicking the last event in
the summary line opens it at that line.

## Emergency stop and model speed

**Emergency stop** stays top right at all times. It is the only filled
button in the Overseer, so it is easy to find.

While the local model is writing, its speed shows under Emergency stop,
for example "38 tok/s". It disappears a second after the last token, so
it never shows 0 or a number left over from an earlier reply.

## Legend

The panel at the bottom left lists each caste with its colour, how many
units it has now, and its job: Warden guards the core, Harvester fetches
sources, Sanitizer checks results, Tripwire watches the edge, Stalker hunts
threats. Red eyes appear only on a real threat.

## Replay strip

The strip along the bottom shows the last 10 minutes, one tick per event:
blue for a fetch, lilac for a result coming in, green for a tripwire check,
red (and taller) for a threat. The line at the right edge is now. Click a
tick to open the event log at that event. The strip does not scrub the
scene back in time.

## Screen readers

The Units button, the Events button, the Dispatch bar's mode, query
("Mission query"), and Dispatch button, Emergency stop, the last event in
the summary line and the replay strip (which opens the newest event) are
all named for screen readers and can be pressed without a mouse. The
summary pieces, model speed and legend rows are read as text.
