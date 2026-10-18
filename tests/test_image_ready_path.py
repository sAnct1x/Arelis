"""The Workspace pane opens the cutout the tool wrote.

image_edit reports ``path`` as ``outputs/images/<file>``, relative to the
data folder. The pane does ``Path(path)``, which uses the process working
directory. An install starts in the install folder, so that relative path
is not the file and the pane says it could not load it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import execute_call
from arelis.tools.image_edit import ImageEditTool
from arelis.workspace import WorkspaceRoots


def _png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (12, 40, 90)).save(path)


class _Bus:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def publish(self, event: object) -> None:
        self.events.append(event)


class _Run:
    def __init__(self) -> None:
        self.bus = _Bus()
        self.max_rounds = 3
        self._look = None
        self._timer = None
        self.tools_used: set[str] = set()
        self._trace: list[str] = []
        self._receipts: list[dict] = []
        self.memory = SimpleNamespace(sink=None, messages=[])
        self.tool_output_chars = 8000
        self._expected_tools: set[str] = set()
        self._fail_replan_used = False
        self.tools = SimpleNamespace(get=lambda _name: None)

    def _tool_message(self, name: str, out: str) -> dict[str, str]:
        return {"role": "tool", "name": name, "content": out}


@pytest.mark.asyncio
async def test_image_edit_ready_event_points_at_the_data_folder_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_app
) -> None:
    """A relative outputs/images path must not be opened from the install cwd."""
    project = tmp_path / "project"
    project.mkdir()
    data = tmp_path / "appdata"
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    monkeypatch.chdir(install)
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "project", "path": str(project)}]}}
    )
    _png(project / "mug.png")
    edited = await ImageEditTool(workspace).run(path="project:mug.png", grayscale=True)
    assert edited.ok
    reported = str(edited.data["path"])
    assert not Path(reported).is_absolute()
    assert reported.startswith("outputs/images/")
    assert not Path(reported).is_file()

    ctx = TurnContext(text="Remove the background from this photo", role="fast")
    scratch = SimpleNamespace(
        text=ctx.text,
        agent_cfg={"tool_summary_inject": False},
        available_all=set(),
        available=set(),
        visible=set(),
        tool_names=set(),
        sources=[],
        ledger=EvidenceLedger(),
        fail_counts={},
        web_search_ok=set(),
        page_ok=set(),
        sms_sent=set(),
        agenda_created=set(),
        exact_need=ctx.exact_need,
        offer_tools=False,
        ollama_tools=[],
        messages=[],
        sms_draft=None,
        email_draft=None,
    )
    loop = _Run()
    await execute_call(
        loop,
        ctx,
        scratch,
        "image_edit",
        {"path": "project:mug.png", "grayscale": True},
        summary="image_edit",
        call_fp="image-edit",
        round_i=1,
        call_i=0,
        fanout_results={0: (4, edited)},
    )

    ready = [event for event in loop.bus.events if event.type == EventType.IMAGE_READY]
    assert len(ready) == 1
    shown = Path(str(ready[0].payload["path"]))
    assert shown.is_absolute()
    assert shown.is_file()
    assert shown.resolve() == (data / reported).resolve()
    assert shown.resolve() == Path(str(edited.data["abs_path"])).resolve()

    from arelis.ui.panels.workspace import WorkspacePanel

    panel = WorkspacePanel()
    try:
        panel.show_image(str(shown))
        qt_app.processEvents()
        assert panel.path_edit.text() == reported
    finally:
        panel.deleteLater()
