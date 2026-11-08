"""Diagnostic contracts for the actual pose fixture, not a replacement bridge."""

import json
import subprocess

import pytest

from tests import pose_bridge_diagnostics as diagnostics


@pytest.mark.parametrize("keepalive", [False, True], ids=["normal-exit", "original-timeout"])
def test_actual_bridge_stderr_markers_preserve_stdout_and_native_exit(
    tmp_path, monkeypatch, keepalive
):
    from tests import test_turn_pose_lines as fixture

    expected = ["thinking", "talking", "done", "listening", "idle"]
    # Build the exact fixture script without launching it twice. Baseline's
    # direct run is intentionally untouched, for a real fail-before check.
    monkeypatch.setattr(
        fixture,
        "run_bridge",
        lambda _: subprocess.CompletedProcess([], 0, json.dumps(expected), ""),
        raising=False,
    )
    fixture.test_bridge_passes_done_and_listening_to_her_poses(tmp_path)
    script = tmp_path / "bridge.js"
    if keepalive:
        script.write_text(
            script.read_text().replace(
                "const sent = [];", "setInterval(() => {}, 1000); const sent = [];"
            )
        )
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            diagnostics.run_bridge(script)
        assert caught.value.timeout == 30
        stdout, stderr = caught.value.stdout, caught.value.stderr
        assert "Node bridge timed out" in "\n".join(caught.value.__notes__)
    else:
        result = diagnostics.run_bridge(script)
        assert result.returncode == 0
        stdout, stderr = result.stdout, result.stderr
    assert json.loads(stdout) == expected
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8")
    rows = [json.loads(line) for line in stderr.splitlines()]
    phases = [row["phase"] for row in rows]
    assert phases == ["entry", "bridge-defined", "transitions-complete", "stdout-call-returned"] + (
        [] if keepalive else ["before-exit", "exit"]
    )
    assert all(row["event"] == "pose-bridge" for row in rows)
    assert rows[0]["pid"] > 0 and rows[0]["node"].startswith("v")
    snapshots = [row["resourceTypes"] for row in rows if "resourceTypes" in row]
    assert snapshots
    for types in snapshots:
        assert types == "unavailable" or (
            isinstance(types, list)
            and len(types) <= 16
            and all(isinstance(kind, str) and len(kind) <= 48 for kind in types)
        )
    if keepalive and snapshots[0] != "unavailable":
        assert "Timeout" in snapshots[0]
    if not keepalive:
        assert rows[-1]["code"] == rows[-2]["code"] == 0


@pytest.mark.parametrize("form", ["text", "bytes", "none"])
def test_timeout_notes_are_bounded_redacted_and_reraise_same_exception(tmp_path, monkeypatch, form):
    payload = (
        'QRhi {"token": "DUMMY_POSE_SECRET"} Authorization: Bearer DUMMY_POSE_SECRET '
        'password="DUMMY_POSE_SECRET" C:\\Users\\dummy\\key 0x12345678 ' + "z" * 10000
    )
    value = payload if form == "text" else payload.encode() if form == "bytes" else None
    exc = subprocess.TimeoutExpired(["node", "bridge.js"], 30, output=value, stderr=value)
    calls = []

    def timed_out(*args, **kwargs):
        calls.append((args, kwargs))
        raise exc

    monkeypatch.setattr(diagnostics.subprocess, "run", timed_out)
    script = tmp_path / "bridge.js"
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        diagnostics.run_bridge(script)
    assert caught.value is exc
    assert exc.stdout is value and exc.stderr is value and exc.timeout == 30
    assert calls == [
        (
            (["node", str(script)],),
            {
                "capture_output": True,
                "text": True,
                "timeout": 30,
                "check": True,
            },
        )
    ]
    note = "\n".join(getattr(exc, "__notes__", []))
    assert "Node bridge timed out" in note
    assert "stdout prefix:" in note and "stderr prefix:" in note
    assert "DUMMY_POSE_SECRET" not in note and "Users" not in note and "0x12345678" not in note
    assert len(note) < 8400
    assert ("<unavailable>" in note) == (form == "none")
    if form != "none":
        assert "<redacted>" in note and "QRhi" in note
