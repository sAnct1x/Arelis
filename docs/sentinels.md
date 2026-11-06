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

