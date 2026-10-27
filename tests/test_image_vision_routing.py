"""Image path helpers + chat_fast_path re-arm for vision/image turns."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.attachments import (
    format_attachments_block,
    route_tool,
    wants_image_edit,
    wants_image_restyle,
    wants_image_surgical,
)
from arelis.core.agent_loop import (
    should_redirect_wander_to_sms,
)
from arelis.core.image_refs import (
    mentions_camera_look,
)
from arelis.core.preflight import detect_intents
from arelis.core.skills import select_skill_ids
from arelis.core.sms_complete import looks_like_image_gen


def test_mentions_camera_look() -> None:
    assert mentions_camera_look("look at the camera")
    assert mentions_camera_look("look at the desk camera")
    assert mentions_camera_look("look at the room webcam")
    assert mentions_camera_look("What do you see?")
    assert mentions_camera_look("check the webcam feed")
    assert mentions_camera_look("Look at this. What is it?")
    assert not mentions_camera_look("describe the image you just generated")
    assert not mentions_camera_look("hello there")
    assert not mentions_camera_look("look at the book")


def _attach_image_turn(ask: str) -> str:
    block = format_attachments_block(
        [
            {
                "path": r"C:\Users\you\Documents\Arelis\data\drops\20260817\paste.png",
                "kind": "image",
            }
        ],
        user_text=ask,
    )
    return f"{block}\n\n{ask}"


def _attach_pdf_turn(ask: str) -> str:
    block = format_attachments_block(
        [
            {
                "path": r"C:\Users\you\Documents\Arelis\data\drops\20261023\report.pdf",
                "kind": "pdf",
            }
        ],
        user_text=ask,
    )
    return f"{block}\n\n{ask}"


def test_pdf_summary_does_not_nudge_document_writer() -> None:
    """A PDF read/summary must name document as the wrong sibling.

    The image rules already say do not call doc_extract/analyze. The PDF
    rule named vision and analyze and left document out, so a summary
    ask called the writer (issue 409). The new line must not itself
    match the create-file intent.
    """
    from arelis.core.claims import detect_document_ask
    from arelis.core.intent_catalog import DOCUMENT

    ask = "summarize this"
    text = _attach_pdf_turn(ask)
    assert "→ doc_extract" in text
    assert "Do not call document" in text
    assert route_tool("pdf", ask) == "doc_extract"
    assert not DOCUMENT.matches(text)
    assert not detect_document_ask(text)
    tools = {t for h in detect_intents(text) for t in h.expected_tools}
    assert "document" not in tools


def test_document_tool_line_says_it_does_not_read_a_pdf() -> None:
    """The model-facing document line must not read as a PDF reader.

    It said "create a formatted document (... pdf)" and nothing about
    reading, so a summary next to an attached PDF still called the writer
    after the attachment rule (issue 409).
    """
    from arelis.core.compact_prompt import skinny_description

    line = skinny_description("document")
    assert line.startswith("write a new file")
    assert "not to read a pdf" in line


def test_vision_does_not_redirect_to_sms_when_sms_is_stale_expected() -> None:
    """Calling vision while a leftover SMS expected-set exists must not rewrite."""
    assert not should_redirect_wander_to_sms("vision", {"send_sms"})
    assert not should_redirect_wander_to_sms("ocr", {"send_sms"})
    assert not should_redirect_wander_to_sms("image", {"send_sms"})
    assert not should_redirect_wander_to_sms("image_edit", {"send_sms"})
    assert not should_redirect_wander_to_sms("camera", {"send_sms"})
    assert should_redirect_wander_to_sms("web_search", {"send_sms"})


def test_vibrant_thumbnail_expects_image_edit_not_generate() -> None:
    """7.2: edit the attached pixels; do not force Comfy generate."""
    ask = "Make this more vibrant and resize it for a YouTube thumbnail."
    text = _attach_image_turn(ask)
    assert wants_image_edit(ask)
    assert not looks_like_image_gen(ask)
    assert not looks_like_image_gen(text)
    hints = detect_intents(text)
    tools = {t for h in hints for t in h.expected_tools}
    kinds = [h.kind for h in hints]
    assert "image_edit" in tools
    assert "image" not in tools
    assert "image_gen" not in kinds
    ids = select_skill_ids(
        ask,
        available_tools={"image", "image_edit", "vision", "web_search"},
    )
    assert "image_edit" in ids
    assert "image" not in ids


def _last_image_history() -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": "saved to outputs/images/arelis_00021_.png",
            "note": "",
        }
    ]


def _assert_routes_image(ask: str, *, gen: bool = True) -> None:
    assert route_tool("image", ask) == "image"
    assert looks_like_image_gen(ask) is gen
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    assert "image" in tools
    assert "image_edit" not in tools
    assert "send_sms" not in tools
    assert "calculator" not in tools
    ids = select_skill_ids(
        ask,
        available_tools={"image", "image_edit", "vision", "web_search", "calculator"},
    )
    assert "image" in ids
    assert "image_edit" not in ids


def _assert_routes_image_edit(ask: str) -> None:
    assert wants_image_edit(ask)
    assert not wants_image_restyle(ask)
    assert not wants_image_surgical(ask)
    assert not looks_like_image_gen(ask)
    assert route_tool("image", ask) == "image_edit"
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    assert "image_edit" in tools
    assert "image" not in tools
    assert "send_sms" not in tools
    assert "calculator" not in tools
    ids = select_skill_ids(
        ask,
        available_tools={"image", "image_edit", "vision", "web_search", "calculator"},
    )
    assert "image_edit" in ids
    assert "image" not in ids


# 1x1 PNG. Same bytes the paperclip bench uses.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _pngs(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path for path in root.rglob("*") if path.is_file()}


async def test_typed_existing_image_is_staged_after_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typed path that is a real image is copied like a paperclip drop.

    The copy of an outside file waits until Allow. A skip leaves the drops
    folder untouched.
    """
    import asyncio

    import arelis.attachments as attachments
    from arelis.core.agent_loop import AgentLoop
    from arelis.core.bus import EventBus
    from arelis.core.events import Event, EventType
    from arelis.core.memory import SessionMemory
    from arelis.core.orchestrator import Orchestrator
    from arelis.tools.base import ToolRegistry
    from arelis.workspace import WorkspaceRoots

    drops = tmp_path / "drops"
    monkeypatch.setattr(attachments, "DROPS_ROOT", drops)

    async def _quiet_run(self, *args, **kwargs):
        return None

    monkeypatch.setattr(AgentLoop, "run", _quiet_run)

    room = tmp_path / "room"
    room.mkdir()
    (room / "plot.png").write_bytes(_PNG)
    outside = tmp_path / "outside"
    outside.mkdir()
    shapes = outside / "shapes.png"
    shapes.write_bytes(_PNG)

    class _Router:
        default_role = "fast"

    persona = Path(__file__).resolve().parents[1] / "arelis" / "persona" / "arelis.md"
    bus = EventBus()
    orch = Orchestrator(
        bus,
        _Router(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {"confirm_timeout_s": 30},
            "workspace": {"roots": [str(room)]},
            "_persona_path": str(persona),
        },
        SessionMemory(),
        workspace=WorkspaceRoots.from_paths([str(room)]),
    )

    await orch.on_user_message(Event(EventType.USER_MESSAGE, {"text": "describe ./plot.png"}))
    staged = str((orch._last_ask or {}).get("text") or "")
    assert "Attachments for this turn" in staged
    assert "(image)" in staged
    assert "→ vision" in staged
    inside_copies = _pngs(drops)
    assert len(inside_copies) == 1

    denied: list[str] = []
    task = asyncio.create_task(
        orch.on_user_message(Event(EventType.USER_MESSAGE, {"text": f"what is in {shapes}"}))
    )
    for _ in range(100):
        if orch._confirm_live:
            break
        await asyncio.sleep(0)
    assert orch._confirm_live
    assert _pngs(drops) == inside_copies
    confirm_id = next(iter(orch._confirm_live))
    await orch.on_confirm_reply(
        Event(EventType.TOOL_CONFIRM_REPLY, {"id": confirm_id, "decision": "skip"})
    )
    await task
    while not bus._queue.empty():
        event = bus._queue.get_nowait()
        if event.type == EventType.ASSISTANT_DONE:
            denied.append(str(event.payload.get("text") or ""))
    assert _pngs(drops) == inside_copies
    assert denied == ["I didn't open that file because it wasn't allowed."]

    task = asyncio.create_task(
        orch.on_user_message(Event(EventType.USER_MESSAGE, {"text": f"what is in {shapes}"}))
    )
    for _ in range(100):
        if orch._confirm_live:
            break
        await asyncio.sleep(0)
    assert orch._confirm_live
    assert _pngs(drops) == inside_copies
    confirm_id = next(iter(orch._confirm_live))
    await orch.on_confirm_reply(
        Event(EventType.TOOL_CONFIRM_REPLY, {"id": confirm_id, "decision": "allow"})
    )
    await task
    opened = str((orch._last_ask or {}).get("text") or "")
    assert "Attachments for this turn" in opened
    assert "(image)" in opened
    assert "→ vision" in opened
    assert len(_pngs(drops)) == 2


