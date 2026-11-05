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
  unit or a whole caste.
- "Have the wardens scan sockets." She gives a caste one task it really
  supports: harvesters fetch a page or search arXiv, Horizons or Wikipedia;
  wardens scan sockets, check a URL or intercept; tripwires watch a folder or
  verify; sanitizers clean text or HTML or inspect an archive. Anything else
  is refused. Sentinels still cannot send your data out.
- "Research exoplanet transits with the sentinels." Harvesters search arXiv
  and Wikipedia. She tells you the mission started, not that it finished;
  its result, or why it failed, shows in the log.
- "Emergency stop the sentinels." Every unit halts at once, with no card to
  click first. Only you can lift it.

Deploy, stop, retask and research ask first in the usual way unless your
own request already asked for them.
