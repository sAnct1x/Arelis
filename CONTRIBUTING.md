# Contributing

Thanks for looking.

## About this project

Arelis is maintained by one person on the side of a full-time university degree
(astrophysics). Roughly a year of on-and-off work. Re-released a month or two
ago. Updates come in bursts around the school calendar.

Help is welcome. The parts where it helps most:

- **Windows testing** — more hardware, more edge cases.
- **Documentation** — first-run confusion, setup pitfalls.
- **Packaging and installer work** — the .exe, signing, dependencies.
- **Reality/astro extras** — the optional spatial and astro features. Source only.

A clear bug report is useful even if you are not writing code. Follow the rest
of this file for what works and what will not land.

## Getting started

New to the codebase? Look for issues labeled `good first issue` - these are
small, self-contained tasks that don't require deep knowledge of the whole
system.

### Dev setup

You'll need Python 3.11+ and [Ollama](https://ollama.com/download).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,voice,browser]"
# Optional extras:
# pip install -e ".[spatial]"  # hand tracking in Reality (not in installer)
# pip install -e ".[astro]"    # 3D solar system (not in installer)
playwright install chromium
git config core.hooksPath .githooks
```

That last line is important - the hooks run lint and personal data checks
before commits. Without it, a lint failure might not show up until you push.

### Running tests

Before opening a pull request:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
```

Both must pass. Type-checking (`mypy`) is installed with the dev extra. CI gates
the packages listed in `tests/mypy_strict_packages.txt` using
`python -m mypy --no-pretty --follow-imports=silent @tests/mypy_strict_packages.txt`.
For other code, run mypy when working on type fixes, not as a blocker for unrelated changes.

## The rule that does not bend

**Nothing that identifies a real person may enter this repository.** Not a
phone number, not a home path, not a consumer email, not a name from your
contacts, not a set of coordinates. Tests count. A fixture is as public as
the rest of the code.

`tests/test_no_personal_data.py` fails the commit if you slip. Use
`5555550123`, `you@example.com`, and `C:/Users/you/...`. Springfield and
Metropolis, Illinois are the towns we keep.

A public repo cannot take a secret back. Deleting the file later does not
erase the clones.

## What will not land

**Nothing about a user leaves their machine unless they aimed it there.**
No analytics. No silent crash report. No model call to a service they did
not set up. `tests/test_egress.py` pins the hosts this code may name.
Adding one is a pull request with a reason, not a line nobody noticed.

**No feature is gated behind a payment.** The program is free software.
Anything sold around it is content, and content does not live here.

**Everyone runs the same application.** There is no private build with
extra tricks.

## The agreement

A pull request means two things.

First, the [Developer Certificate of Origin](https://developercertificate.org/).
You wrote it, or you otherwise have the right to send it under this
licence. Sign off your commits:

```
git commit -s -m "your message"
```

Second, a licence grant. You keep the copyright. You also grant the
maintainer a perpetual, worldwide, non-exclusive, irrevocable licence to
use, reproduce, modify, and distribute the contribution, including the
right to license it under different terms later. That is a licence, not
an assignment. You can still use your own work however you like.

The grant is there so this project can adopt a later AGPL, or fix a
licence clash with a dependency, without hunting down every person who
ever landed a line. If you are not comfortable with that, open an issue
instead. A clear bug report is genuinely useful.

## Pull request guidelines

Open a pull request once your change is tested and passing lint. The PR
template will guide you through what to include.

Ruff is pinned in `pyproject.toml` so a new release won't turn an untouched
tree red on your unrelated change. The pre-commit hook in `.githooks` runs
lint and personal data checks, so local failures catch early.

Type-checking (`mypy`) is pinned the same way. CI gates the packages listed
in `tests/mypy_strict_packages.txt`. To check all code (a report, not a gate):

```powershell
.\.venv\Scripts\python -m mypy
```

### Tests

Every change lands with tests a person can read. The name states the
user-visible property. The docstring says which defect it exists to catch.
`test_bare_sam_does_not_steal_sam_brightly` still makes sense at eleven at
night a year from now. `test_contact_matching_2` does not.

Prefer behaviour over internals. A test on a private attribute passes
until someone refactors, then it costs an hour.

### Paths

Two rules, both invisible from a checkout, which is why they are written
down.

**Mutable files go through `arelis/paths.py`.** Use `state_dir()`,
`logs_dir()`, `outputs_dir()`, or `models_dir()`. Never a path derived
from where the package sits. In a checkout those are the same folder, so
the wrong version works. Installed, the folder above the package is
`site-packages`, where a standard user cannot write, an update replaces
everything, and every account shares it. `tests/test_user_data_dir.py`
fails a new module that gets this wrong.

**Shipped files that are not Python must live inside `arelis/` and be
listed in `[tool.setuptools.package-data]`.** Setuptools packages nothing
else. Arelis once shipped with no icon because the file was committed,
loaded in four places, and missing from every install.
`tests/test_packaged_assets.py` watches that.

If it works here, that is not yet proof it works installed.

### Commit messages

Why, in the imperative, with a short lowercase prefix: `voice:`, `ui:`,
`tests:`. The body is the reasoning a reader cannot recover from the
diff. Do not credit a tool in the message.

## Reporting a bug

A security hole is different. See [SECURITY.md](SECURITY.md). Private
report. Not a public issue.

For ordinary bugs: what you did, what you expected, what happened. Logs
stay on your machine (`%LOCALAPPDATA%\Arelis\logs` installed, `logs/`
from source). Read them before you attach anything. An issue is public.

The supported desktop is Windows. How the installer is built:
[win-installer/README.md](win-installer/README.md).
