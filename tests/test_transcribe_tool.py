"""transcribe tool: workspace audio via an injected STT callable.

Roadmap 5.4. Sherpa/Whisper already exist for voice. This file drives
TranscribeTool.run with a mock transcribe_fn so a helper that looks right
while never calling the engine — or worse, constructing Whisper mid-turn —
is the bug.

Mutants this file is supposed to catch:

1. path escape (`../` or an absolute sibling) — must refuse, must not
   open the file or call STT.
2. missing transcribe_fn / cold stt returns ok=True (empty transcript)
   instead of the honest GPU refusal.
3. huge file is sent to STT instead of being refused.
4. unsupported suffix (txt / mp4) is transcribed anyway.
5. a helper is unit-tested and Tool.run is never called.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools.transcribe import TranscribeTool
from arelis.workspace import RootEntry, WorkspaceRoots


def _workspace(tmp_path: Path) -> tuple[WorkspaceRoots, Path]:
    project = tmp_path / "project"
    project.mkdir()
    workspace = WorkspaceRoots([RootEntry(name="project", path=project.resolve())])
    return workspace, project


def _clip(project: Path, name: str = "talk.wav", payload: bytes = b"RIFF....") -> Path:
    dest = project / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return dest


class _Recorder:
    def __init__(self, text: str = "hello from the clip") -> None:
        self.text = text
        self.calls: list[Path] = []

    def __call__(self, path: Path) -> str:
        self.calls.append(Path(path))
        return self.text


class _ColdSTT:
    """Would load Whisper if anyone called it. Tests must not."""

    def loaded(self) -> bool:
        return False

    def _transcribe_blocking(self, path: str, purpose: str = "turn") -> str:
        raise AssertionError("must not construct Whisper mid-turn")

    def transcribe(self, path: Path) -> str:
        raise AssertionError("must not construct Whisper mid-turn")


class _WarmSTT:
    def __init__(self, text: str = "from warm stt") -> None:
        self.text = text
        self.calls: list[str] = []

    def loaded(self) -> bool:
        return True

    def _transcribe_blocking(self, path: str, purpose: str = "turn") -> str:
        self.calls.append(path)
        return self.text


@pytest.mark.asyncio
async def test_file_runs_injected_fn_not_a_helper(tmp_path: Path) -> None:
    """Mutant: a private helper is tested and Tool.run is never called."""
    workspace, project = _workspace(tmp_path)
    clip = _clip(project)
    rec = _Recorder("the meeting is at four")
    tool = TranscribeTool(workspace, transcribe_fn=rec)
    result = await tool.run(path="talk.wav")
    assert result.ok, result.output
    assert "the meeting is at four" in result.output
    assert result.data["path"] == str(clip.resolve())
    assert result.data["empty"] is False
    assert rec.calls == [clip.resolve()]


@pytest.mark.asyncio
async def test_default_action_is_file(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)
    _clip(project)
    rec = _Recorder()
    tool = TranscribeTool(workspace, transcribe_fn=rec)
    result = await tool.run(action="file", path=str(project / "talk.wav"))
    assert result.ok, result.output
    assert rec.calls


@pytest.mark.asyncio
async def test_path_escape_is_refused(tmp_path: Path) -> None:
    """Mutant: `../` is joined and a sibling file is sent to STT."""
    workspace, project = _workspace(tmp_path)
    _clip(project)
    planted = project.parent / "outside.wav"
    planted.write_bytes(b"vault-code-9911-secret")
    rec = _Recorder("LEAKED")
    tool = TranscribeTool(workspace, transcribe_fn=rec)

    for raw in (
        "../outside.wav",
        r"..\outside.wav",
        "talk.wav/../../outside.wav",
        str(planted),
    ):
        result = await tool.run(path=raw)
        assert not result.ok, f"escape must fail for {raw!r}: {result.output}"
        assert "LEAKED" not in result.output
        assert "9911" not in result.output
        assert "outside" in result.output.lower() or "workspace" in result.output.lower()

    assert rec.calls == []


@pytest.mark.asyncio
async def test_missing_fn_is_not_empty_ok(tmp_path: Path) -> None:
    """Mutant: no engine → ok=True with an empty transcript."""
    workspace, project = _workspace(tmp_path)
    _clip(project)
    tool = TranscribeTool(workspace)
    result = await tool.run(path="talk.wav")
    assert result.ok is False
    assert "voice engine not loaded" in result.output
    assert "Whisper" in result.output
    assert result.output.strip()


@pytest.mark.asyncio
async def test_cold_stt_is_not_called(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)
    _clip(project)
    tool = TranscribeTool(workspace, stt=_ColdSTT())
    result = await tool.run(path="talk.wav")
    assert result.ok is False
    assert "voice engine not loaded" in result.output


@pytest.mark.asyncio
async def test_warm_stt_is_used_when_fn_missing(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)
    clip = _clip(project)
    stt = _WarmSTT("from the already-loaded ear")
    tool = TranscribeTool(workspace, stt=stt)
    result = await tool.run(path="talk.wav")
    assert result.ok, result.output
    assert "from the already-loaded ear" in result.output
    assert stt.calls == [str(clip.resolve())]


@pytest.mark.asyncio
async def test_injected_fn_wins_over_cold_stt(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)
    _clip(project)
    rec = _Recorder("prefer the callable")
    tool = TranscribeTool(workspace, transcribe_fn=rec, stt=_ColdSTT())
    result = await tool.run(path="talk.wav")
    assert result.ok, result.output
    assert "prefer the callable" in result.output


@pytest.mark.asyncio
async def test_huge_file_is_refused(tmp_path: Path) -> None:
    """Mutant: size cap is skipped and STT sees the blob."""
    workspace, project = _workspace(tmp_path)
    _clip(project, payload=b"x" * 200)
    rec = _Recorder()
    tool = TranscribeTool(workspace, transcribe_fn=rec, max_bytes=64)
    result = await tool.run(path="talk.wav")
    assert not result.ok
    assert "refuses" in result.output.lower() or "over" in result.output.lower()
    assert rec.calls == []


@pytest.mark.asyncio
async def test_unsupported_suffix_is_refused(tmp_path: Path) -> None:
    """Mutant: any file under the root is sent to STT."""
    workspace, project = _workspace(tmp_path)
    notes = project / "notes.txt"
    notes.write_text("do not read this as audio", encoding="utf-8")
    video = project / "clip.mp4"
    video.write_bytes(b"ftyp")
    rec = _Recorder("should not run")
    tool = TranscribeTool(workspace, transcribe_fn=rec)

    text = await tool.run(path="notes.txt")
    assert not text.ok
    assert "unsupported" in text.output.lower()
    assert "should not run" not in text.output

    movie = await tool.run(path="clip.mp4")
    assert not movie.ok
    assert "video" in movie.output.lower()
    assert "ffmpeg" in movie.output.lower() or "audio" in movie.output.lower()
    assert "should not run" not in movie.output

    assert rec.calls == []


@pytest.mark.asyncio
async def test_max_chars_truncates(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)
    _clip(project)
    rec = _Recorder("x" * 400)
    tool = TranscribeTool(workspace, transcribe_fn=rec)
    result = await tool.run(path="talk.wav", max_chars=80)
    assert result.ok, result.output
    assert result.data["truncated"] is True
    assert result.data["chars"] == 400
    assert "truncated" in result.output
    assert result.output.count("x") < 400


def test_schema_and_risk() -> None:
    assert TranscribeTool.name == "transcribe"
    assert TranscribeTool.risk == "read"
    props = TranscribeTool.parameters_schema["properties"]
    assert props["action"]["enum"] == ["file"]
    assert "path" in props
    assert "max_chars" in props
    assert "path" in TranscribeTool.parameters_schema["required"]
