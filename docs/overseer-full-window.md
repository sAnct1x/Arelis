# Overseer: full window, chat off

When you open the Overseer (View menu, then **Sentinels**), the swarm gets
the whole Sentinels window and chat turns off until you close it.

## Full window

The 3D scene runs edge to edge. There is no side panel and no boxed
header: the title and the status line (threats, defenders, units by caste,
warrants, last event) sit as text over the sky. Every control from before
is still there; the list and the event log just fold away until you want
them. Panels keep a small margin (2 percent of the window) from the edges.

Opening or closing a drawer never moves the camera or resizes the scene.

## Glow

Only the brightest things in the scene glow: unit eyes, the source cores
and fetch beams. Hulls, lanes and the perimeter never do. The glow is a soft
halo a few pixels wide around each eye. Edges are not smoothed
(antialiasing is off), which keeps the Overseer within its frame budget.

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

The bar at the bottom centre works like the chat composer: pick a mode
(multi, arXiv, Horizons, Wikipedia, security audit), type the query, then
press Enter or **Dispatch**. The result of the request shows just under
the bar.

**Events** (bottom left) opens the event log above the bar, with the same
filters, search, and Repeats toggle as before. Clicking **Last event** in
the status line opens it at that line.

## Emergency stop

**Emergency stop** stays top right at all times. It is the only filled
button in the Overseer, so it is easy to find.

## Screen readers

The Units button, the Events button, the Dispatch bar's mode, query
("Mission query"), and Dispatch button, and Emergency stop are all named
for screen readers and can be pressed without a mouse.
