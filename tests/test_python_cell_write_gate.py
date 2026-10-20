"""A Python cell cannot reach the runner's module, hook flag, or write policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools.python_exec import PythonTool
from arelis.workspace import RootEntry, WorkspaceRoots


@pytest.mark.asyncio
async def test_cell_cannot_reach_runner_internals(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    tool = PythonTool(
        WorkspaceRoots([RootEntry(name="proj", path=root)]), science_io=True
    )
    result = await tool.run(
        code=(
            "found = []\n"
            "sys = None\n"
            "objs = list(vars().values())\n"
            "try:\n"
            "    objs.extend(list(vars(np.lib).values()))\n"
            "except Exception:\n"
            "    pass\n"
            "for obj in objs:\n"
            "    try:\n"
            "        mapping = vars(obj)\n"
            "    except Exception:\n"
            "        continue\n"
            "    if 'sys' not in mapping:\n"
            "        continue\n"
            "    maybe = mapping['sys']\n"
            "    try:\n"
            "        if 'modules' in vars(maybe):\n"
            "            sys = maybe\n"
            "            break\n"
            "    except Exception:\n"
            "        continue\n"
            "if sys is None:\n"
            "    raise ValueError('sys not reachable')\n"
            "markers = ('_IN_HOOK', '_SCIENCE_IO', '_WORK_WRITE', '_WORK_READ')\n"
            "to_scan = list(sys.modules.values())\n"
            "to_scan.append(dict(vars()))\n"
            "for name in list(sys.modules):\n"
            "    if 'python_cell_runner' in str(name):\n"
            "        found.append(str(name))\n"
            "for obj in to_scan:\n"
            "    try:\n"
            "        mapping = vars(obj)\n"
            "    except Exception:\n"
            "        mapping = obj if isinstance(obj, dict) else None\n"
            "    if mapping is None:\n"
            "        continue\n"
            "    for key in markers:\n"
            "        if key in mapping:\n"
            "            found.append(key)\n"
            "    try:\n"
            "        items = list(mapping.values())\n"
            "        keys = list(mapping)\n"
            "    except Exception:\n"
            "        continue\n"
            "    for key in keys:\n"
            "        if 'python_cell_runner' in str(key):\n"
            "            found.append(str(key))\n"
            "    for val in items:\n"
            "        if isinstance(val, str) and str(val).endswith('python_cell_runner.py'):\n"
            "            found.append(val)\n"
            "        try:\n"
            "            childmap = vars(val)\n"
            "        except Exception:\n"
            "            continue\n"
            "        for key in markers:\n"
            "            if key in childmap:\n"
            "                found.append(key)\n"
            "        try:\n"
            "            childvals = list(childmap.values())\n"
            "            childkeys = list(childmap)\n"
            "        except Exception:\n"
            "            continue\n"
            "        for key in childkeys:\n"
            "            if 'python_cell_runner' in str(key):\n"
            "                found.append(str(key))\n"
            "        for child in childvals:\n"
            "            if isinstance(child, str) and str(child).endswith('python_cell_runner.py'):\n"
            "                found.append(child)\n"
            "if found:\n"
            "    raise ValueError(str(found))\n"
            "'isolated'\n"
        )
    )
    assert result.ok is True, result.output
    assert "isolated" in result.output
