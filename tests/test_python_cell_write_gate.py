"""A Python cell cannot write outside the room results folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools.python_exec import PythonTool
from arelis.workspace import RootEntry, WorkspaceRoots


@pytest.mark.asyncio
async def test_write_outside_results_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    tool = PythonTool(
        WorkspaceRoots([RootEntry(name="proj", path=root)]), science_io=True
    )
    result = await tool.run(
        code=(
            "libmap = vars(np.lib)\n"
            "utils = libmap['utils'] if 'utils' in libmap else libmap['_utils_impl']\n"
            "sys = vars(utils)['sys']\n"
            "for mod in sys.modules.values():\n"
            "    try:\n"
            "        mapping = vars(mod)\n"
            "    except TypeError:\n"
            "        continue\n"
            "    if '_IN_HOOK' in mapping:\n"
            "        mapping['_IN_HOOK'] = True\n"
            f"handle = open({str(outside)!r}, 'w')\n"
            "handle.write('x')\n"
            "handle.close()\n"
        )
    )
    assert result.ok is False, result.output
    assert not outside.exists()
