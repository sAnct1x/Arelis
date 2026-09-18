"""The packages we claim are fully typed, checked the way CI checks them.

Repo-wide mypy is a report — thousands of errors, `|| true`, no gate. These
few packages are different: they are at zero, and a package that is allowed
to regress is not clean. The list lives in `mypy_strict_packages.txt` so one
line adds a package to both this test and the CI step.

The second test is the one that matters. Repo mypy config is deliberately
permissive, and a gate inherits that config. If a flag or a config key ever
makes mypy shrug at a plain type error, the first test still passes on a
clean package and the gate quietly stops gating. So we hand the same command
a file we know is wrong and require it to say so.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRICT_LIST = Path(__file__).parent / "mypy_strict_packages.txt"

# Same flags as the "Mypy strict gate" step in .github/workflows/ci.yml.
_FLAGS = ["--no-pretty", "--follow-imports=silent"]


def _mypy(*args: str) -> subprocess.CompletedProcess[str]:
    """Run mypy from the repo root so pyproject config and relative paths resolve."""
    return subprocess.run(
        [sys.executable, "-m", "mypy", *_FLAGS, *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_strictly_typed_packages_are_clean() -> None:
    assert STRICT_LIST.exists(), "strict package list is missing"
    listed = [
        line.strip()
        for line in STRICT_LIST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert listed, "an empty list makes the gate vacuous"
    for entry in listed:
        assert (ROOT / entry).exists(), f"{entry} is gated but does not exist"

    done = _mypy(f"@{STRICT_LIST}")
    assert done.returncode == 0, (
        f"gated packages must stay at zero mypy errors:\n{done.stdout}\n{done.stderr}"
    )
    # Exit 0 on nothing checked would be a pass with no work done. mypy exits 2
    # on a missing or empty path, so this is a belt on the existence loop above.
    assert "no issues found in 0 source" not in done.stdout


def test_the_gate_still_fails_on_a_plain_type_error(tmp_path: Path) -> None:
    """Proof the gate can fail. Without this the suite only ever sees it pass."""
    broken = tmp_path / "broken.py"
    broken.write_text("def f() -> int:\n    return 'not an int'\n", encoding="utf-8")

    done = _mypy(str(broken))
    assert done.returncode != 0, (
        "the gate's flags and config let an obvious type error through, so a "
        f"regression in a gated package would not fail CI either:\n{done.stdout}"
    )
    assert "return-value" in done.stdout
