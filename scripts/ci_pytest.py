"""The two pytest steps inside the CI test job.

xdist runs everything except the serial marker. The serial step runs right
after, in the same job, so a timing-sensitive test does not share a worker.
On Linux the xdist step records branch coverage and the serial step appends,
so the combined report stays one file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def paths_from_env() -> list[str]:
    raw = os.environ.get("RUNNER_TEMP", "")
    if not raw:
        return []
    path = Path(raw) / "ci-tier-paths.txt"
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def command(mode: str, *, coverage: bool, paths: list[str]) -> list[str]:
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    if mode == "xdist":
        cmd += ["-n", "auto", "-m", "not serial", "--junitxml=pytest-results.xml"]
        if coverage:
            cmd += ["--cov=arelis", "--cov-branch", "--cov-report=term-missing"]
    elif mode == "serial":
        cmd += ["-m", "serial", "--junitxml=pytest-results-serial.xml"]
        if coverage:
            cmd += [
                "--cov=arelis",
                "--cov-branch",
                "--cov-append",
                "--cov-report=term-missing",
            ]
    else:
        raise ValueError(mode)
    return cmd + paths


def finish(mode: str, code: int) -> int:
    """pytest exits 5 when a tier collected no serial tests. That is success."""
    if mode == "serial" and code == 5:
        return 0
    return code


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in {"xdist", "serial"}:
        print("usage: ci_pytest.py xdist|serial", file=sys.stderr)
        return 2
    mode = args[0]
    coverage = os.environ.get("RUNNER_OS") == "Linux"
    cmd = command(mode, coverage=coverage, paths=paths_from_env())
    print(" ".join(cmd))
    code = subprocess.call(cmd)
    if mode == "serial" and code == 5:
        print("no serial tests in this tier")
    return finish(mode, code)


if __name__ == "__main__":
    sys.exit(main())
