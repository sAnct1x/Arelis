"""Local MOCKED protocol proofs, NOT Windows native validation or debugger execution."""

import io
import json
from types import SimpleNamespace

import pytest

from tools import windows_gdb_validation as proof


@pytest.mark.parametrize("kind", ["symbol", "module", "malformed"])
def test_frame_output_is_allowlisted_before_persistence(kind, capsys):
    secret = "DUMMY_PRIVATE_SENTINEL"
    record = (
        'frame={level="0",addr="0x1234ABCD",func="QEventLoop::exec",'
        'from="C:/DUMMY_PRIVATE_SENTINEL/Qt6Core.dll",args="DUMMY_PRIVATE_SENTINEL"}'
    )
    if kind == "symbol":
        record = record.replace("QEventLoop::exec", secret)
    elif kind == "module":
        record = record.replace("Qt6Core.dll", secret + ".dll")
    else:
        record += ',frame={func="broken"'
    if kind == "malformed":
        with pytest.raises(proof.ProofError):
            proof.frames(record)
        return
    sanitized = proof.frames(record)
    persisted = json.dumps(sanitized)
    assert secret not in persisted
    assert "0x1234ABCD" not in persisted and "args" not in persisted and "C:/" not in persisted
    assert sanitized[0]["symbol"] == ("unresolved" if kind == "symbol" else "QEventLoop::exec")
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("limit", ["frames", "threads", "bytes", "line", "deadline"])
def test_diagnostic_budgets_fail_closed(limit):
    assert (proof.MAX_THREADS, proof.MAX_FRAMES, proof.MAX_BYTES, proof.WALL_SECONDS) == (
        16,
        12,
        262144,
        24,
    )
    if limit == "frames":
        with pytest.raises(proof.ProofError):
            proof.frames(",".join(['frame={func="QEventLoop::exec"}'] * 13))
    elif limit == "threads":
        debugger = SimpleNamespace(
            command=lambda _: ",".join(f'thread-id="{n}"' for n in range(17))
        )
        with pytest.raises(proof.ProofError):
            proof.collect(debugger, {})
    elif limit in {"bytes", "line"}:
        data = b"x" * 8194 if limit == "line" else (b"x" * 8190 + b"\n") * 34
        stream = io.BytesIO(data)
        pipe = proof.BoundedPipe(stream)
        assert pipe.failed.wait(2)
        assert stream.tell() < len(data)
    else:
        pipe = proof.BoundedPipe(io.BytesIO(b"ignored\n"))
        with pytest.raises(proof.ProofError):
            pipe.take(proof.time.monotonic() - 1)


@pytest.mark.parametrize("useful", [True, False])
def test_protocol_requires_both_owned_threads_and_useful_qt_frames(useful):
    def command(text):
        if text == "-thread-list-ids":
            return '1^done,thread-ids={thread-id="1",thread-id="2"}'
        thread = text.split()[-1] if text.startswith("-thread-info") else text.split()[2]
        if text.startswith("-thread-info"):
            return f'2^done,threads=[{{id="{thread}",target-id="Thread 999.{thread}"}}]'
        symbol = "QEventLoop::exec" if useful else "DUMMY_SECRET_SYMBOL"
        return f'3^done,stack=[frame={{level="0",addr="0x1234",func="{symbol}"}}]'

    debugger = SimpleNamespace(command=command)
    if not useful:
        with pytest.raises(proof.ProofError):
            proof.collect(debugger, {"gui": 1, "render": 2})
    else:
        result = proof.collect(debugger, {"gui": 1, "render": 2})
        assert set(result) == {"gui", "render"}
        assert "0x1234" not in json.dumps(result)


@pytest.mark.parametrize("failure", [None, "attach", "unwind", "detach", "resume", "stale", "exit"])
def test_validation_detaches_and_requires_post_detach_resume_and_normal_exit(monkeypatch, failure):
    child = SimpleNamespace(pid=999, stdin=io.BytesIO(), stdout=None, returncode=None)
    child.poll = lambda: child.returncode

    def kill_child():
        child.returncode = -9

    def wait_child(timeout):
        assert timeout > 0
        if child.returncode is None:
            child.returncode = 1 if failure == "exit" else 0

    child.kill, child.wait = kill_child, wait_child
    events = []

    class FakeDebugger:
        def __init__(self, executable, deadline):
            assert executable == "existing-gdb"
            assert deadline <= proof.time.monotonic() + 24
            self.version = "17.1"
            self.process = SimpleNamespace(returncode=None)
            self.process.poll = lambda: self.process.returncode

            def kill_debugger():
                events.append("kill-gdb")
                self.process.returncode = -9

            self.process.kill = kill_debugger
            self.process.wait = lambda timeout: self.process.returncode

        def start(self):
            pass

        def command(self, command):
            if not command.startswith("-target-attach"):
                return
            events.append("attach")
            if failure == "attach":
                raise proof.ProofError("DUMMY_SECRET_ERROR")

        def detach(self, deadline):
            events.append("detach")
            assert deadline <= proof.time.monotonic() + 2
            if failure == "detach":
                raise proof.ProofError("DUMMY_SECRET_ERROR")

    class FakePipe:
        def __init__(self, _):
            self.first = True
            self.reads = 0

        def take(self, _):
            if self.first:
                self.first = False
                return json.dumps({"gui": 1, "render": 2, "gtick": 1, "rtick": 1, "ack": 0})
            assert "detach" in events and child.stdin.getvalue() == b"resume\n"
            self.reads += 1
            if failure == "stale":
                if self.reads == 1:
                    return json.dumps({"gui": 1, "render": 2, "gtick": 2, "rtick": 2, "ack": 0})
                raise proof.ProofError
            if failure == "resume":
                raise proof.ProofError("DUMMY_SECRET_ERROR")
            return json.dumps({"gui": 1, "render": 2, "gtick": 2, "rtick": 2, "ack": 1})

    def collect(*_):
        if failure == "unwind":
            raise proof.ProofError("DUMMY_SECRET_ERROR")
        return {
            "gui": [{"symbol": "QEventLoop::exec"}],
            "render": [{"symbol": "QSGRenderThread::run"}],
        }

    monkeypatch.setattr(proof, "sys", SimpleNamespace(platform="win32", executable="python"))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_OS", "Windows")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "rhi")
    monkeypatch.setattr(proof.shutil, "which", lambda _: "existing-gdb")
    monkeypatch.setattr(proof.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(proof, "Debugger", FakeDebugger)
    monkeypatch.setattr(proof, "BoundedPipe", FakePipe)
    monkeypatch.setattr(proof, "collect", collect)
    result = proof.validate()
    assert result["status"] == ("failed" if failure else "passed")
    assert "detach" in events and "kill-gdb" in events
    assert "DUMMY_SECRET_ERROR" not in json.dumps(result)
    if failure is None:
        assert result["resumed"] and result["normal_exit"] and result["detached"]
        assert child.stdin.getvalue() == b"resume\nquit\n"
    if failure == "detach":
        assert not result["detached"] and child.returncode == -9


def test_nonhosted_invocation_never_starts_debugger_or_child(monkeypatch):
    monkeypatch.setattr(proof, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(proof.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    assert proof.validate()["status"] == "failed"


@pytest.mark.parametrize("detach_state", ["empty", "error", "retained"])
def test_real_mi_parser_discards_streams_and_requires_detach_ack(monkeypatch, detach_state, capsys):
    transcript = b'~"GNU gdb (GDB) 17.1\\n"\n~"DUMMY_PRIVATE_SENTINEL 0x1234ABCD"\n1^done\n' + (
        b'2^error,msg="DUMMY_PRIVATE_SENTINEL"\n'
        if detach_state == "error"
        else b'2^done\n3^done,threads=[{id="1"}]\n'
        if detach_state == "retained"
        else b"2^done\n3^done,threads=[]\n"
    )
    process = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(transcript))
    monkeypatch.setattr(proof.subprocess, "Popen", lambda *a, **k: process)
    debugger = proof.Debugger("existing-gdb", proof.time.monotonic() + 1)
    debugger.start()
    debugger.command("-gdb-version")
    assert debugger.version == "17.1"
    if detach_state == "empty":
        debugger.detach(proof.time.monotonic() + 1)
    else:
        with pytest.raises(proof.ProofError):
            debugger.detach(proof.time.monotonic() + 1)
    assert process.stdin.getvalue() == (
        b"1-gdb-version\n2-target-detach\n"
        + (b"" if detach_state == "error" else b"3-thread-info\n")
    )
    assert capsys.readouterr() == ("", "")


def test_standalone_source_preserves_native_and_privacy_boundaries():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(proof))
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not names & {"winId", "createWinId", "dump", "dumpMemory", "eval", "setdefault"}
    assert 'os.environ.get("QT_QPA_PLATFORM")' in inspect.getsource(proof)
    assert 'os.environ.get("QT_QUICK_BACKEND")' in inspect.getsource(proof)
    source = inspect.getsource(proof)
    for forbidden in (
        "QSG_RHI_BACKEND",
        "-data-read-memory",
        "-stack-list-variables",
        "-stack-list-arguments",
    ):
        assert forbidden not in source
    assert '"-nx"' in source and '"-nh"' in source
    assert '"-gdb-set print frame-arguments none"' in source
    assert '"-gdb-set print entry-values no"' in source
    assert '"-gdb-set auto-load off"' in source
    assert '"-gdb-set debuginfod enabled off"' in source
    assert 'os.environ.get("GITHUB_ACTIONS") != "true"' in source


@pytest.mark.parametrize("failure", ["debugger-kill", "debugger-wait", "reader-start"])
def test_owned_process_cleanup_is_independent_even_after_partial_debugger_start(
    monkeypatch, failure
):
    events = []

    class Process:
        def __init__(self, role):
            self.role = role
            self.pid = 999
            self.stdin = io.BytesIO()
            self.stdout = role
            self.returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            events.append(self.role + "-kill")
            if self.role == "gdb" and failure == "debugger-kill":
                raise OSError("DUMMY_PRIVATE_CLEANUP_ERROR")
            self.returncode = -9

        def wait(self, timeout):
            events.append(self.role + "-wait")
            assert 0 < timeout <= 1
            if self.role == "gdb" and failure in {"debugger-kill", "debugger-wait"}:
                raise proof.subprocess.TimeoutExpired("DUMMY_PRIVATE_CLEANUP_ERROR", timeout)
            return self.returncode

    child, gdb = Process("child"), Process("gdb")

    class Pipe:
        def __init__(self, stream):
            self.stream = stream
            if stream == "gdb" and failure == "reader-start":
                raise RuntimeError("DUMMY_PRIVATE_CLEANUP_ERROR")

        def take(self, _):
            if self.stream == "child":
                return json.dumps({"gui": 1, "render": 2, "gtick": 1, "rtick": 1, "ack": 0})
            raise proof.ProofError

    monkeypatch.setattr(proof, "sys", SimpleNamespace(platform="win32", executable="python"))
    for key, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_OS": "Windows",
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QUICK_BACKEND": "rhi",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(proof.shutil, "which", lambda _: "existing-gdb")
    monkeypatch.setattr(
        proof.subprocess, "Popen", lambda args, **kwargs: child if args[0] == "python" else gdb
    )
    monkeypatch.setattr(proof, "BoundedPipe", Pipe)
    result = proof.validate()
    assert result["status"] == "failed"
    assert "gdb-kill" in events and "gdb-wait" in events
    assert "child-kill" in events and "child-wait" in events
    assert result["cleanup"]["child"] == "exited"
    assert result["cleanup"]["debugger"] == (
        "exited" if failure == "reader-start" else "unconfirmed"
    )
    assert "DUMMY_PRIVATE_CLEANUP_ERROR" not in json.dumps(result)
