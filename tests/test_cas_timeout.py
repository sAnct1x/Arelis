"""The CAS promised a timeout on every action and gave one to three.

`cas.py` opens with "runs the named action under a timeout". Only
integrate, dsolve and sum actually got one, via a child process that can
be killed. solve, diff, simplify, factor, expand, limit, series, gradient
and directional all ran unbounded on the calling thread.

That is not theoretical. Measured on this machine, each of these was still
running after twenty seconds:

    solve(x**40 - x**17 + 3*x**5 - 1, x)
    simplify(sum(sin(x**k)/cos(x**(k+1)) for k in 1..13))
    series(exp(sin(tan(x))), x, 0, 40)

None is an exotic input for someone doing physics homework, and the failure
mode is the one the user rates worst: the glass stops answering, Stop does
nothing, and a core spins until the process is killed. The same shape as the
python_exec hang found the same afternoon, and for a related reason — a
timeout that was written down but not wired to the path that needed it.

The fix must not cost latency on the fast path, because avoiding a 2s process
spawn is precisely why these actions stay in-process. Hence a call-only
tracer: returning None from the trace function disables per-line tracing,
where the expense lives, and SymPy makes enough calls that the deadline still
lands. `test_the_fast_path_is_not_slowed` is the guard on that bargain.

series is the exception that came back. The tracer only runs on Python
calls, and a series expand spends its time inside integer gcd, which is C.
The future then gives up and leaves the thread running. That thread kept
the interpreter busy through a later import and the macOS suite died there.
series now uses the same killable child as integrate.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from arelis.tools.cas import CasTool


@pytest.mark.asyncio
async def test_a_runaway_solve_gives_up_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arelis.tools.cas as cas

    monkeypatch.setattr(cas, "_TIMEOUT_S", 1.0)
    started = time.monotonic()
    result = await CasTool().run(action="solve", expr="x**40 - x**17 + 3*x**5 - 1")
    elapsed = time.monotonic() - started

    assert result.ok is False
    assert elapsed < 8.0, f"took {elapsed:.1f}s; the deadline did not fire"
    assert result.data.get("fail_class") == "fail:timeout"


@pytest.mark.asyncio
async def test_the_timeout_message_forbids_inventing_an_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CAS that gave up is the single most tempting moment to make
    something up, so the refusal has to say so out loud."""
    import arelis.tools.cas as cas

    monkeypatch.setattr(cas, "_TIMEOUT_S", 1.0)
    result = await CasTool().run(action="solve", expr="x**40 - x**17 + 3*x**5 - 1")
    assert "did not finish" in result.output
    assert "invent" in result.output.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,expr",
    [
        ("simplify", "sin(x**1)/cos(x**2) + sin(x**3)/cos(x**4) + sin(x**5)/cos(x**6)"),
        ("series", "exp(sin(tan(x)))"),
    ],
)
async def test_the_other_untimed_actions_are_bounded_too(
    monkeypatch: pytest.MonkeyPatch, action: str, expr: str
) -> None:
    """Not just solve. The gap was every action outside _SPAWN_ACTIONS."""
    import arelis.tools.cas as cas

    monkeypatch.setattr(cas, "_TIMEOUT_S", 0.001)
    started = time.monotonic()
    result = await CasTool().run(action=action, expr=expr, n=20)
    elapsed = time.monotonic() - started

    assert elapsed < 8.0, f"{action} took {elapsed:.1f}s"
    if not result.ok:
        assert result.data.get("fail_class") in {"fail:timeout", "fail:parse"}


# --------------------------------------------------------------------------
# And the ordinary answers still arrive, quickly
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,expr,expected",
    [
        ("diff", "x**3", "3*x**2"),
        ("solve", "x**2 - 4", "2"),
        ("simplify", "(x**2 - 1)/(x - 1)", "x + 1"),
        ("factor", "x**2 - 1", "x - 1"),
        ("expand", "(x + 1)**2", "x**2"),
    ],
)
async def test_the_everyday_actions_still_answer(
    action: str, expr: str, expected: str
) -> None:
    result = await CasTool().run(action=action, expr=expr)
    assert result.ok, result.output
    assert expected in result.output


@pytest.mark.asyncio
async def test_the_fast_path_is_not_slowed() -> None:
    """The bargain behind the in-process path, stated as a test.

    These actions skip the child process to avoid a spawn on every quadratic.
    If bounding them reintroduced that cost, the fix would have traded a rare
    hang for a constant tax on the common case.
    """
    started = time.monotonic()
    for _ in range(5):
        result = await CasTool().run(action="diff", expr="x**3 + sin(x)")
        assert result.ok
    elapsed = time.monotonic() - started
    assert elapsed < 4.0, f"five derivatives took {elapsed:.1f}s"


def _cas_worker_still_inside_compute() -> bool:
    """True when some thread in this process is still inside the CAS worker."""
    import sys

    for frame in sys._current_frames().values():
        seen = frame
        while seen is not None:
            filename = seen.f_code.co_filename.replace("\\", "/")
            if filename.endswith("arelis/tools/cas.py") and seen.f_code.co_name in {
                "_traced",
                "_compute",
            }:
                return True
            seen = seen.f_back
    return False


@pytest.mark.asyncio
async def test_a_pathological_series_is_killed_with_its_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The macOS run was this: series sat in integer gcd, the thread was
    abandoned, and a later test timed out while that thread still held the
    interpreter.

    Patching gcd to a single long sleep reproduces the hole on a laptop.
    A call tracer cannot raise during that sleep. If series is still
    in-process, the worker is alive after the tool has already given up.
    """
    import multiprocessing

    import sympy.core.intfunc as intfunc

    import arelis.tools.cas as cas

    monkeypatch.setattr(cas, "_TIMEOUT_S", 0.4)

    def _hold(*_args: object, **_kwargs: object) -> int:
        time.sleep(30)
        return 1

    monkeypatch.setattr(intfunc, "number_gcd", _hold)
    before = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    result = await CasTool().run(action="series", expr="exp(sin(tan(x)))", n=20)
    elapsed = time.monotonic() - started

    assert result.ok is False
    assert result.data.get("fail_class") == "fail:timeout"
    assert elapsed < 8.0, f"took {elapsed:.1f}s; the child was not killed"

    deadline = time.monotonic() + 1.0
    leftover: list[object] = []
    while time.monotonic() < deadline:
        leftover = [p for p in multiprocessing.active_children() if p.pid not in before]
        if not leftover and not _cas_worker_still_inside_compute():
            break
        await asyncio.sleep(0.05)
    assert leftover == []
    assert not _cas_worker_still_inside_compute()


@pytest.mark.asyncio
async def test_series_of_sine_is_the_opening_terms() -> None:
    result = await CasTool().run(action="series", expr="sin(x)", n=6)
    assert result.ok, result.output
    text = str(result.data.get("result") or "").replace(" ", "")
    assert "x**3/6" in text
    assert "x**5/120" in text


@pytest.mark.asyncio
async def test_series_keeps_the_point_it_was_given() -> None:
    """The expansion point has to reach the child. Without it, every series is at 0."""
    result = await CasTool().run(action="series", expr="exp(x)", n=3, at="1")
    assert result.ok, result.output
    text = str(result.data.get("result") or "").replace(" ", "")
    assert "E" in text
    assert "x**2" in text
    assert text != "x**2/2+x+1"


@pytest.mark.asyncio
async def test_an_integral_still_goes_to_the_child_process() -> None:
    """The spawn path predates this and must be left alone: a thread deadline
    cannot stop integrate(), which is the reason it was built."""
    result = await CasTool().run(action="integrate", expr="2*x", wrt="x")
    assert result.ok, result.output
    assert "x**2" in result.output
