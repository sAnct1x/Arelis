"""Check that Task Scheduler accepts the XML build_task_xml produces.

Not part of the test suite, because it writes to the machine's task store.
Run it by hand after changing build_task_xml: the unit tests can prove the XML
says what it should, but only schtasks can prove the schema is valid, and a
schema error means scheduling fails silently at the very last step.

    .\\.venv\\Scripts\\python.exe scripts\\schtasks_smoke.py

Registers a task pointing at a job id that does not exist, queries it, then
deletes it. Nothing it registers could ever do anything.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from arelis.jobs.schedule import build_task_xml
from arelis.jobs.store import Job

NAME = "\\Arelis\\__smoketest__"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["schtasks", *args], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        print(f"  schtasks {args[0]} -> exit {completed.returncode}: {detail}")
    return completed


def _job(**kwargs) -> Job:
    base = {"id": "__smoketest__", "name": "Arelis smoke test", "prompt": "never runs"}
    return Job(**{**base, **kwargs})


# One per schedule shape the tool can produce. Each is a different XML form,
# and each is a different way Task Scheduler can reject us.
SHAPES: list[tuple[str, Job]] = [
    ("every day", _job()),
    ("chosen weekdays", _job(days=["monday", "friday"])),
    ("twice a day", _job(times=["08:00", "18:00"])),
    ("every 2 hours on weekdays", _job(days=["monday", "friday"], every_minutes=120)),
    ("monthly on the 1st and 15th", _job(repeat="monthly", days_of_month=[1, 15])),
    (
        "one-off, deletes itself",
        _job(repeat="once", date="2099-08-15", times=["15:00"]),
    ),
]


def check(label: str, job: Job) -> bool:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".xml", encoding="utf-16", delete=False, newline="\r\n"
    )
    handle.write(build_task_xml(job))
    handle.close()
    try:
        created = run("/Create", "/TN", NAME, "/XML", handle.name, "/F")
        if created.returncode != 0:
            print(f"  FAILED: {label}\n")
            return False
        query = run("/Query", "/TN", NAME, "/FO", "LIST")
        for line in query.stdout.splitlines():
            if line.lower().startswith(("next run time:", "schedule type:")):
                print(f"  {line.strip()}")
        print(f"  OK: {label}\n")
        return True
    finally:
        run("/Delete", "/TN", NAME, "/F")
        Path(handle.name).unlink(missing_ok=True)


def main() -> int:
    failures = [label for label, job in SHAPES if not check(label, job)]
    if failures:
        print(f"FAILED {len(failures)} of {len(SHAPES)}: {', '.join(failures)}")
        return 1
    print(f"PASSED: Task Scheduler accepted all {len(SHAPES)} schedule shapes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
