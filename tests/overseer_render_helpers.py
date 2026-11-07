"""Bound native Qt work to one test and one fresh application lifetime.

Like the surface render probe, use a child rather than trying to catch a
segfault in Python. A failed/blank renderer must fail, never silently skip.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CHILD = "ARELIS_OVERSEER_RENDER_NODE"


def isolated_render(*, software: bool = False):
    """Keep native crashes, grabs and teardown out of reusable xdist workers."""

    def decorate(test):
        @functools.wraps(test)
        def run(*args, **kwargs):
            node = f"{Path(test.__code__.co_filename).relative_to(_ROOT)}::{test.__name__}"
            if os.environ.get(_CHILD) == node:
                return test(*args, **kwargs)
            env = dict(os.environ, **{_CHILD: node})
            # This child runs one explicit node, serially, even if its parent
            # uses xdist or selection flags. Serial pytest needs no xdist option.
            env.pop("PYTEST_ADDOPTS", None)
            if software:
                # This probe contains only the 2D HUD, not the Quick3D scene.
                # Qt's software Quick backend supports offscreen pixel grabs.
                env["QT_QUICK_BACKEND"] = "software"
            cmd = [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", node]
            try:
                import coverage
            except ImportError:
                active = None
            else:
                active = coverage.Coverage.current()
            with tempfile.TemporaryDirectory(prefix="overseer-render-") as tmp:
                data_path = str(Path(tmp) / ".coverage")
                if active is not None:
                    cmd = [
                        sys.executable,
                        "-m",
                        "coverage",
                        "run",
                        *(["--branch"] if active.config.branch else []),
                        "--source=arelis",
                        f"--data-file={data_path}",
                        "-m",
                        *cmd[2:],
                    ]
                result = subprocess.run(
                    cmd,
                    cwd=_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if active is not None and Path(data_path).is_file():
                    data = coverage.CoverageData(basename=data_path)
                    data.read()
                    active.get_data().update(data)
                output = result.stdout + result.stderr
                assert result.returncode == 0, output
                assert "1 passed" in result.stdout, output

        return run

    return decorate
