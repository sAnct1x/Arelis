"""CAS tool — AST-safe SymPy, timeout, no eval sandbox holes."""

from __future__ import annotations

import os
import time
from unittest import mock

import pytest

from arelis.tools import build_tool_registry
from arelis.tools.cas import CasTool, parse_cas_expr
from arelis.workspace import WorkspaceRoots


def test_parse_rejects_import_and_attributes() -> None:
    for expr in (
        "__import__('os').system('echo hi')",
        "().__class__",
        "open('/etc/passwd')",
        "(lambda x: x)(1)",
        "os.system('echo hi')",
    ):
        with pytest.raises(ValueError):
            parse_cas_expr(expr)


def test_parse_rejects_huge_expression() -> None:
    with pytest.raises(ValueError, match="too long"):
        parse_cas_expr("x+" * 300 + "1")


@pytest.mark.asyncio
async def test_integrate_x_squared_sin_x() -> None:
    tool = CasTool()
    result = await tool.run(action="integrate", expr="x**2 * sin(x)", wrt="x")
    assert result.ok, result.output
    text = result.output.lower().replace(" ", "")
    assert "cos" in text and "sin" in text


@pytest.mark.asyncio
async def test_diff_and_simplify() -> None:
    tool = CasTool()
    d = await tool.run(action="diff", expr="x**3", wrt="x")
    assert d.ok
    assert "3" in d.output and "x" in d.output
    s = await tool.run(action="simplify", expr="(x**2 - 1)/(x - 1)")
    assert s.ok
    assert "x" in s.output


@pytest.mark.asyncio
async def test_no_closed_form_is_honest() -> None:
    tool = CasTool()
    hold = await tool.run(action="integrate", expr="sin(sin(x))", wrt="x")
    assert not hold.ok
    assert "closed form" in hold.output.lower() or "will not invent" in hold.output.lower()


@pytest.mark.asyncio
async def test_dsolve_first_order() -> None:
    tool = CasTool()
    result = await tool.run(
        action="dsolve",
        expr="diff(y(x), x) - y(x)",
        symbol="y",
    )
    assert result.ok, result.output
    assert "exp" in result.output.lower() or "e**" in result.output.lower() or "C" in result.output


@pytest.mark.asyncio
async def test_timeout_refuses_instead_of_guessing(monkeypatch) -> None:
    def _slow(*_args, **_kwargs):
        time.sleep(2)

    monkeypatch.setattr("arelis.tools.cas._compute", _slow)
    monkeypatch.setattr("arelis.tools.cas._TIMEOUT_S", 0.05)
    tool = CasTool()
    result = await tool.run(action="integrate", expr="x**2")
    assert not result.ok
    assert "timed out" in result.output.lower()
    assert "guess" in result.output.lower() or "will not" in result.output.lower()


@pytest.mark.asyncio
async def test_import_payload_never_calls_os_system() -> None:
    tool = CasTool()
    with mock.patch.object(os, "system") as system:
        result = await tool.run(expr="__import__('os').system('echo pwned')")
        assert not result.ok
        system.assert_not_called()


def test_cas_is_registered_without_confirm(tmp_path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert registry.get("cas") is not None
    assert not registry.needs_confirm("cas", {"expr": "x**2", "action": "integrate"})
    jobs = build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, allow_send=False
    )
    assert jobs.get("cas") is not None
    assert jobs.get("units") is not None
