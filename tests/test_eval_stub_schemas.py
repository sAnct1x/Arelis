"""The offline stubs must declare what the real tools declare.

The eval harness exists to catch tool-layer regressions offline. It cannot do
that while its stubs present a surface the model never sees: they declared no
parameters at all, which ``cross_tool_arg_error`` reads as "accepts nothing", so
every scripted argument was rejected as foreign and fifteen tests went quietly
green-to-red without anyone noticing the gate was the cause.

A stub whose schema has drifted from its tool is worse than no stub, because the
eval then reports on a surface that does not exist. These tests fail on drift.
"""

from __future__ import annotations

import pytest

from arelis.config import load_config
from arelis.core.tool_args import cross_tool_arg_error, schema_keys
from arelis.eval.harness import _STUB_SCHEMAS, foundation_registry, stub_schema


def _real_registry():
    from arelis.llm import build_router
    from arelis.tools import build_tool_registry

    config = load_config()
    router = build_router(config)
    return build_tool_registry(
        config, allow_send=True, provider=router.provider, router=router
    )


def test_every_mirrored_schema_matches_the_real_tool() -> None:
    real = _real_registry()
    names = set(real.names())
    checked = 0
    for name, (required, props) in sorted(_STUB_SCHEMAS.items()):
        if name not in names:
            # Growth-track stub: no real tool to mirror yet.
            continue
        schema = getattr(real.get(name), "parameters_schema", None) or {}
        assert set(props) == schema_keys(schema), (
            f"{name}: stub declares {sorted(props)}, tool declares "
            f"{sorted(schema_keys(schema))}"
        )
        assert set(required) == set(schema.get("required") or ()), (
            f"{name}: stub requires {sorted(required)}, tool requires "
            f"{sorted(schema.get('required') or ())}"
        )
        checked += 1
    assert checked >= 20, f"only {checked} stubs checked against real tools"


def test_a_mirrored_stub_no_longer_rejects_its_own_arguments() -> None:
    """The regression that hid a gate: an open schema rejected everything."""
    for name, args in (
        ("web_search", {"query": "artemis launch date"}),
        ("calculator", {"expression": "17*19"}),
        ("cas", {"action": "integrate", "expr": "x**2", "wrt": "x"}),
        ("units", {"action": "convert", "quantity": "5 ft 8 in", "to": "meter"}),
        ("plot", {"action": "line", "xs": "1,2,3", "ys": "1,4,9"}),
        ("catalog", {"action": "arxiv", "query": "gravitational waves"}),
        ("tasks", {"action": "list"}),
        ("send_sms", {"to": "wife", "body": "dinner is at 7"}),
    ):
        declared = schema_keys(stub_schema(name))
        assert declared, f"{name} declares nothing"
        assert cross_tool_arg_error(name, args, declared=declared) is None


def test_the_gate_still_catches_a_genuinely_foreign_call() -> None:
    """Mirroring must not have turned the gate off."""
    declared = schema_keys(stub_schema("calculator"))
    err = cross_tool_arg_error("calculator", {"to": "wife", "body": "hi"}, declared=declared)
    assert err is not None
    assert "send_sms" in err


@pytest.mark.parametrize("name", sorted(_STUB_SCHEMAS))
def test_the_foundation_registry_agrees_with_the_mirror(name: str) -> None:
    registry = foundation_registry()
    if name not in set(registry.names()):
        pytest.skip(f"{name} is not in the foundation registry")
    tool = registry.get(name)
    assert schema_keys(tool.parameters_schema) == set(_STUB_SCHEMAS[name][1])
