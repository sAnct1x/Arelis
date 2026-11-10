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
import time
from pathlib import Path

from tests.overseer_render_diagnostics import diagnostic_output, run_child

_ROOT = Path(__file__).resolve().parents[1]
_CHILD = "ARELIS_OVERSEER_RENDER_NODE"


def isolated_render(*, software: bool = False, native_gl: bool = False):
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
            if sys.platform == "win32" and not software:
                # Quick 3D needs a real native window: the offscreen QPA
                # cannot create a D3D swapchain for a QQuickView.
                env["QT_QPA_PLATFORM"] = "windows"
            if software:
                # This probe contains only the 2D HUD, not the Quick3D scene.
                # Qt's software Quick backend supports offscreen pixel grabs.
                env["QT_QUICK_BACKEND"] = "software"
            elif native_gl and env.get("DISPLAY"):
                # renderStats.drawCallCount stays 0 on the offscreen QPA even
                # when renderPassCount is live. A real window under xvfb is
                # needed to read the draw cap. Set xcb explicitly so the
                # child's conftest setdefault("offscreen") does not win.
                env["QT_QPA_PLATFORM"] = "xcb"
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                "-o",
                "addopts=",
                "-p",
                "tests.overseer_render_diagnostics",
                "-q",
                node,
            ]
            try:
                import coverage
            except ImportError:
                active = None
            else:
                active = coverage.Coverage.current()
            with tempfile.TemporaryDirectory(prefix="overseer-render-") as tmp:
                data_path = str(Path(tmp) / ".coverage")
                env["ARELIS_OVERSEER_DIAGNOSTICS"] = tmp
                # Logging only: never select a different QPA/RHI/render backend.
                env["QSG_INFO"] = "1"
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
                env["ARELIS_OVERSEER_DEADLINE"] = str(time.monotonic() + 60)
                try:
                    result = run_child(
                        cmd,
                        cwd=_ROOT,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    exc.add_note(diagnostic_output(Path(tmp)))
                    raise
                if active is not None and Path(data_path).is_file():
                    data = coverage.CoverageData(basename=data_path)
                    data.read()
                    active.get_data().update(data)
                output = result.stdout + result.stderr
                if result.returncode != 0 or "1 passed" not in result.stdout:
                    output += diagnostic_output(Path(tmp))
                assert result.returncode == 0, output
                assert "1 passed" in result.stdout, output

        return run

    return decorate
