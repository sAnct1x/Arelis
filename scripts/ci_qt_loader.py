"""Bounded, read-only xcb loader/provider evidence; never a test verdict.

Run as a module from the checkout. Reuse the reviewed diagnostic sanitizer;
importing it does not create a Qt application or install its pytest hooks.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from tests.overseer_render_diagnostics import sanitize

LIMIT = 16 * 1024
TOOL_TIMEOUT = 10
# Only plugin dependency providers and the three existing workflow packages.
PACKAGES = (
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-util1",
    "libxcb-image0",
    "libxcb-keysyms1",
    "libxcb-randr0",
    "libxcb-render-util0",
    "libxcb-shm0",
    "libxcb-sync1",
    "libxcb-xfixes0",
    "libxcb-render0",
    "libxcb-shape0",
    "libxcb-xkb1",
    "libxcb1",
    "libxkbcommon0",
    "libxkbcommon-x11-0",
    "libx11-xcb1",
    "libx11-6",
    "libgl1",
    "libegl1",
    "libdbus-1-3",
)


def inspect_tool(name, args):
    tool = shutil.which(name)
    if tool is None:
        return {"status": "tool-missing"}
    # Fixed metadata commands only. Bound elapsed time and bytes read/emitted;
    # private scratch output is discarded, including on tool failure/timeout.
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(
                [tool, *args],
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=TOOL_TIMEOUT,
                check=False,
            )
            record = {"status": "completed", "returncode": result.returncode}
        except subprocess.TimeoutExpired:
            record = {"status": "timeout"}
        except OSError as exc:
            record = {"status": "unavailable", "error_type": type(exc).__name__}
        output.seek(0)
        raw = output.read(LIMIT + 1)
    record["output"] = sanitize(raw[:LIMIT].decode("utf-8", errors="replace"))
    record["truncated"] = len(raw) > LIMIT
    return record


def plugin_path():
    from PySide6.QtCore import QLibraryInfo

    return (
        Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / "platforms" / "libqxcb.so"
    )


def main():
    report = {"purpose": "advisory-xcb-loader-metadata"}
    try:
        plugin = plugin_path()
        if plugin.is_file():
            report["plugin"] = "present-at-Qt-PluginsPath/platforms/libqxcb.so"
            report["ldd"] = inspect_tool("ldd", [str(plugin)])
        else:
            report["plugin"] = "missing-at-Qt-PluginsPath/platforms/libqxcb.so"
    except Exception as exc:
        # Do not print import exceptions or private installation paths.
        report["plugin"] = "Qt-API-unavailable"
        report["error_type"] = type(exc).__name__
    report["packages"] = inspect_tool(
        "dpkg-query",
        ["-W", "-f=${binary:Package}\t${db:Status-Status}\t${Version}\n", *PACKAGES],
    )
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0  # Advisory only. The workflow also contains native/import failure.


if __name__ == "__main__":
    raise SystemExit(main())
