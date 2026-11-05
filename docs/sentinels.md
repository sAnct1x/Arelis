# Sentinels window

Arelis starts Sentinel in the background when she launches. The Sentinels
window lets you watch the swarm live: the 3D view, the roster by caste,
the mission picker, and the searchable log console.

## Opening it

View menu, then **Sentinels**. In Filament the same item is in the field
menu. It opens as its own window, separate from the main one, and takes
its colours from the theme you are using (Night, Sodium, or Filament).

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

Arelis can read the swarm for you. She can only look; she cannot deploy,
stop, or retask sentinels yet, and she can never undo an emergency stop.

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
