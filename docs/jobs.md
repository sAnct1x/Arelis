# Scheduled jobs

A job is a prompt that runs later, unattended, and emails you the
answer. Windows Task Scheduler is what actually fires it. You can
manage jobs from the calendar tile's **jobs** tab (Ctrl+7), or just
ask her to set one up for you.

Mail has to be connected first (`data/secrets.yaml`) — the scheduling
tool isn't even offered until it is. A job that has no way to send
mail simply won't run.

## What a job actually holds

- **prompt** — What to do, written as a fresh ask each time. There's
  no chat history attached to it.
- **when** — Once, weekly (specific days and times), monthly, or
  repeating throughout the day.
- **role** — Fast or Research. Same underlying models as chat.
- **recipient** — Where the digest gets sent. Leave it blank and it
  goes to your default mail recipient.

A one-off job with a specific date runs exactly once, then deletes
itself.

Worth noting: a morning briefing isn't actually a model turn at all.
Weather, unread mail, and open loops get pulled together through a
fixed template (`schedule action create_briefing`), and the runner
recognizes it via the sentinel prompt `__arelis_briefing__`.

## What it won't do

There's nobody around to press **allow** on a scheduled run, so the
job runner answers every confirmation card with skip — and it never
even registers the tools that would need your input in the first
place: sending mail or SMS, her browser, vision, camera, clipboard,
OCR, plotting, documents, the 3D solar system, Earth, Reality, memory
writes, contacts, rooms, research reports, or calendar writes.

What it *will* do: search, scrape, fetch pages, check the weather,
run CAS and unit conversions, query catalogs, use the calculator, and
run a short Python cell. Reading from the workspace still works fine
too. Anything that writes something, generates an image, or would
normally pop up an Allow card just gets skipped — and it's named in
the email you receive, so you know exactly what to fix in the prompt
if you want it included.

Jobs never resume a room, either. Every run starts as a fresh
session, with no room context carried over.

## How it's stored

Jobs live in `data/jobs.yaml`, under your records folder —
`%LOCALAPPDATA%\Arelis\data` if installed, or `data\` in the
repository if you're running from source. It's meant to be
hand-editable.

Windows keeps a matching scheduled task at `\Arelis\<job-id>`.
Creating or deleting a job through Arelis updates both sides at once.
If you ever end up with a task that has no matching yaml row, or a
yaml row with no task, that's drift — `arelis/jobs/schedule.py` can
tell you what Task Scheduler actually has registered.

The task itself runs `pythonw.exe -m arelis --run-job <id>` (using
the installed copy's own interpreter, if that's what you're running),
so there's no console window flashing up. `StartWhenAvailable` is set
too, so if your machine was asleep at 7pm, the job still fires once
it wakes up.

Logs land in `logs/jobs.log`, but only for `--run-job` runs
specifically. The last status of each job also gets written back onto
its row in the yaml.

## Running two copies on one PC

An installed copy of Arelis and a source checkout don't share the
same `jobs.yaml` — but Task Scheduler names its tasks by job id
alone, so editing jobs from the checkout can accidentally repoint a
live task at your working tree instead of the installed copy. Setting
`ARELIS_DATA_DIR` (which `scripts\run_dev_ui.ps1` does automatically,
sandboxing things at `%LOCALAPPDATA%\Arelis-dev`) keeps the checkout
from stepping on the installed copy's tasks.

## Related

- Architecture: [architecture.md](architecture.md)
- Mail setup: copy `data/secrets.example.yaml` → `data/secrets.yaml`
- Calendar OAuth is handled separately:
  [calendar-oauth.md](calendar-oauth.md)
