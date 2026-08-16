# Launch the checkout against a sandbox data root, for working on Arelis rather than
# using it.
#
# Why this exists
# ===============
#
# The checkout does not share a data root with an installed Arelis. user_data_dir() sends
# a checkout to the repository root and an install to %LOCALAPPDATA%\Arelis, so they are
# already separate profiles. What this script separates is the checkout from *itself*.
#
# Running from the repository means the repository root is the profile: data\profile.yaml,
# data\contacts.yaml, data\secrets.yaml, data\memory.db and data\jobs.yaml are the real
# ones, not fixtures. Launching a half-finished feature there writes to them.
#
# The failure that actually bites is scheduled jobs. A task holds one absolute path, and
# tasks are named after the job, so both copies want the same task. Nothing thrashes in
# steady state -- each copy records the launcher it registered with under its own data root
# and repoints only when that record disagrees with itself -- but a copy claims every task
# in its jobs.yaml at two moments: the first launch after a fresh install, when it has no
# record yet, and any time you create or edit a job in it. Neither copy knows the other
# exists, so there is nothing to arbitrate. Editing a job here would move your real 23:00
# run to this working tree, and a scheduled task that fails shows nobody anything.
#
# ARELIS_DATA_DIR settles it structurally rather than by care: jobs are read from jobs.yaml
# inside the data root, so a sandbox without one has nothing to claim at either moment. Its
# runner record lives in its own root too.
#
# What you get
# ============
#
# A separate, initially empty Arelis: no conversations, no memory, no contacts, no
# persona tuning, no saved jobs, no OAuth tokens. That is the point twice over. It is
# safe to break, and it is the only way to see the first run a stranger gets, which is
# now the least-tested path in the program and the one that matters most.
#
# Delete the whole directory whenever you want a fresh first run. Nothing in it is
# precious, which is exactly what distinguishes it from the real one.

$ErrorActionPreference = "Stop"

$env:ARELIS_DATA_DIR = Join-Path $env:LOCALAPPDATA "Arelis-dev"

Write-Host "Arelis (development)" -ForegroundColor Cyan
Write-Host "  program : $(Split-Path -Parent $PSScriptRoot)"
Write-Host "  data    : $env:ARELIS_DATA_DIR"
Write-Host "  no real profile, no real memory, no scheduled jobs." -ForegroundColor DarkGray

# Everything about actually starting it -- finding the virtualenv, forcing a real Windows
# Qt surface -- already lives next door. Duplicating it here would mean two launchers
# drifting apart, and the difference between them is meant to be the one line above.
& (Join-Path $PSScriptRoot "run_ui.ps1") @args
