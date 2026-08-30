# Scheduled jobs

A job is a prompt that runs later, with nobody watching, and emails the
answer. Windows Task Scheduler fires it. The calendar tile has a
**jobs** tab (Ctrl+7). You can also ask her to set one up.

Mail has to be connected first (`data/secrets.yaml`). The schedule tool
is not offered until it is. A job that cannot send mail does not run.

## What you get

| | |
|---|---|
| **prompt** | What to do, written as a fresh ask. No chat history. |
| **when** | Once, weekly (days + times), monthly, or repeating through the day. |
| **role** | `fast` or `research`. Same chips as chat. |
| **recipient** | Where the digest goes. Blank means your default mail recipient. |

A one-off with a date runs once and then deletes itself.

A **morning briefing** is not a model turn. Weather, unread mail, and
open loops are a fixed template (`schedule` action `create_briefing`).
The runner recognises the sentinel prompt `__arelis_briefing__`.

## What it will not do

There is no person to press **allow**. The runner answers every confirm
card with skip, and it never registers the tools that would need you:

Send mail / SMS, her browser, vision, camera, clipboard, OCR, plot,
document, solar, earth, Reality's plate, memory writes, contacts, rooms,
research reports, calendar writes.

It **will** search, scrape, fetch, do weather, CAS, units, catalogs,
calculator, and a short `python` cell. Workspace reads still work.
Writes, image generation, and anything else that opens an Allow card are
skipped and named in the email so you can fix the prompt.

Jobs never resume a room. Each run is a fresh session.

## How it is stored

`data/jobs.yaml` under your records folder: `%LOCALAPPDATA%\Arelis\data`
installed, or `data\` in the repository from source. Hand-editable on
purpose.

Windows keeps a matching task at `\Arelis\<job-id>`. Creating or
deleting a job updates both. A task with no yaml row, or a yaml row with
no task, is drift — `arelis/jobs/schedule.py` can list what Task
Scheduler actually has.

The task runs `pythonw.exe -m arelis --run-job <id>` (installed: the
copy's own interpreter). No console flash. `StartWhenAvailable` is set,
so a machine that was asleep at 7pm still runs it when it wakes.

Logs: `logs/jobs.log` for `--run-job` only. Last status also lives on
the yaml row.

## Two copies on one PC

An installed Arelis and a source checkout do not share `jobs.yaml`, but
Task Scheduler names tasks by job id. Editing jobs in the checkout can
repoint a live task at the working tree. `ARELIS_DATA_DIR` (and
`scripts\run_dev_ui.ps1`, which sandboxes at `%LOCALAPPDATA%\Arelis-dev`)
keeps the checkout from claiming the installed tasks.

## Related

- Architecture: [architecture.md](architecture.md)
- Mail: copy `data/secrets.example.yaml` → `data/secrets.yaml`
- Calendar OAuth is separate: [calendar-oauth.md](calendar-oauth.md)
