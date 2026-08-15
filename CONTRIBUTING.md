# Contributing to Arelis

Thank you for looking. This file covers three things: what the project will and
will not accept, the agreement your contribution comes under, and how to get a
change to the point where it can be merged.

## The one rule that has no exceptions

**Nothing that identifies a real person may enter this repository.** Not a
phone number, not a home directory path, not an email address at a consumer
provider, not a name from your contacts, not a set of coordinates. This applies
to test fixtures as much as to shipped code — a fixture is published exactly as
widely as anything else.

This is enforced rather than requested. `tests/test_no_personal_data.py` fails
on all of the above, and a pre-commit hook runs it. If it fails on your change,
use an obviously fictional value: `5555550123` for a phone number,
`you@example.com` for an address, `C:/Users/you/...` for a path.

The reason is not tidiness. A repository is public the instant it is pushed,
and a mistake found a month later cannot be recalled — it survives in every
clone and every fork, and deleting the file does not remove it.

## What Arelis will not do

Some things are settled and a pull request cannot reopen them.

**Nothing about a user leaves their machine unless the user aimed it
somewhere themselves.** No analytics, no crash reports sent without being
shown to the person first, no "anonymous" usage pings, no model calls to a
service the user did not configure. `tests/test_egress.py` pins the list of
hosts this application may contact, and adding one is a deliberate act that
has to be justified in the pull request, not a line slipped into a diff.

**No feature is gated behind a payment.** The code is free software and stays
that way. Anything sold around Arelis is content, and content does not live in
this repository.

**Everyone runs the same application.** There is no private build with extra
capability. If a feature is worth having, it ships to everybody.

## The agreement

By opening a pull request you agree to two things.

First, the **Developer Certificate of Origin**: that you wrote the contribution
or otherwise have the right to submit it under the project's licence. Certify
this by signing off your commits:

```
git commit -s -m "your message"
```

which appends a `Signed-off-by:` line. The full text of the DCO is at
<https://developercertificate.org/>.

Second, a **licence grant**: you grant the maintainer a perpetual, worldwide,
non-exclusive, irrevocable licence to use, reproduce, modify and distribute
your contribution, including the right to license it under different terms in
future. You keep your copyright — this is a licence, not an assignment, and you
may continue to use your own work however you wish.

That second one is asymmetric, and it is worth saying plainly why it is asked
for rather than leaving you to guess. Without it, a project with many
contributors can never change its licence at all, because doing so would
require tracking down and getting agreement from every person who ever landed a
patch. That means it could not adopt a later version of the AGPL, and could not
resolve a licence incompatibility with a dependency it needs. If you are not
comfortable granting it, please open an issue describing the change instead —
a well-written bug report is genuinely valuable, and costs you nothing.

## Getting a change merged

Set up a working copy:

```
python -m venv .venv
.venv\Scripts\pip install -e ".[dev,voice,browser]"
git config core.hooksPath .githooks
```

That last line matters. The hooks are tracked in `.githooks` rather than
`.git/hooks` so they survive a clone, but git will not use them until it is
pointed there.

Before opening a pull request:

```
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
```

Both must be clean. The ruff version is pinned exactly in `pyproject.toml`, so
a new ruff release cannot turn an untouched tree red on your unrelated change.

### Tests

Every change lands with tests, and they are expected to be readable. The
convention here is that a test's name states the user-visible property it
protects, and its docstring explains the defect it exists to catch. A test
named `test_bare_sam_does_not_steal_sam_brightly` tells you what broke and what
must not break again; `test_contact_matching_2` tells you nothing when it fails
at eleven at night a year from now.

Prefer testing behaviour over internals. A test that asserts on a private
attribute passes for as long as nobody refactors, and then costs an hour.

### Commit messages

Write prose that explains *why*, in the imperative, with a short lowercase
prefix naming the area — `voice:`, `ui:`, `tests:`. The body is where the
reasoning goes: what was wrong, what you considered, what you rejected and on
what grounds. A reader six months from now has the diff already; what they
cannot recover is what you knew at the time.

Do not include attribution to any tool used to write the change.

## Reporting a bug

Open an issue describing what you did, what you expected and what happened.
Logs are written under `logs/` next to the application and stay there; attach
the relevant part if it helps, but **read it first** — it may contain your file
paths or the text of your own messages, and an issue is public.

A crash reporter that assembles this for you, shows you the whole thing, and
sends nothing until you say so, is planned but not built. Until it exists,
deciding what to share is unfortunately your job.
