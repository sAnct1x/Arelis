"""The offline board must grade against the tool surface that actually ships.

`harness.py` mirrors each real tool's declared parameters into `_STUB_SCHEMAS`
so a scripted call is validated the same way a live one would be. Nothing kept
that mirror honest: the harness docstring has promised this file since the
mirror was written, and the file did not exist. A stub that accepts arguments
the real tool rejects turns every scenario using it into decoration.

The registry here is the full shippable set: attended, with a router, the VL
model treated as installed, and desktop included. A live session can omit
desktop (not Windows) or vision and camera (no VL model). This file is
checking that the stubs still match tools that ship, not that this machine
would offer them.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from arelis.config import load_config
from arelis.eval.harness import _STUB_SCHEMAS, foundation_registry
from arelis.tools import build_tool_registry

# Tools that need provider credentials from data/secrets.yaml. conftest points
# ARELIS_DATA_DIR at a throwaway root on purpose, so these never register under
# pytest and never will in CI. They are named here rather than skipped silently:
# an unexplained exemption is how a guard file stops guarding.
CREDENTIAL_GATED = frozenset({"send_sms", "send_email", "inbox", "inbound_sms"})


@pytest.fixture(scope="module")
def real_tools() -> dict[str, Any]:
    """Every tool that can ship, not the smaller set this host would offer."""
    router = SimpleNamespace(provider=SimpleNamespace(list_models=None))
    config = load_config()
    config["_vl_model_installed"] = True
    config["_session_platform"] = "win32"
    registry = build_tool_registry(
        config, allow_send=True, attended=True, router=router
    )
    return {name: registry.get(name) for name in registry.names()}


def test_the_credential_gated_list_is_not_stale(real_tools: dict[str, Any]) -> None:
    """If one of these starts registering under pytest, stop exempting it."""
    now_present = sorted(CREDENTIAL_GATED & set(real_tools))
    assert not now_present, (
        f"{now_present} now register without credentials — drop them from "
        "CREDENTIAL_GATED so their schemas get checked like everything else."
    )


def _schema(tool: Any) -> dict[str, Any]:
    return getattr(tool, "parameters_schema", None) or {}


def test_every_stub_names_a_real_tool(real_tools: dict[str, Any]) -> None:
    """A stub with no counterpart grades scenarios against a tool that is gone."""
    stubs = set(foundation_registry().names())
    orphans = sorted(stubs - set(real_tools) - CREDENTIAL_GATED)
    assert not orphans, (
        f"foundation_registry stubs {orphans} do not exist in the real registry. "
        "Either the tool was removed and the stub outlived it, or the stub is "
        "named wrong — both make every scenario using it meaningless."
    )


def test_mirrored_required_args_match_the_real_tool(real_tools: dict[str, Any]) -> None:
    """A stub requiring less than the real tool lets a broken call score green."""
    drift: list[str] = []
    for name, (required, _props) in sorted(_STUB_SCHEMAS.items()):
        tool = real_tools.get(name)
        if tool is None:
            continue
        real_required = set(_schema(tool).get("required") or ())
        if set(required) != real_required:
            drift.append(
                f"{name}: stub requires {sorted(required)}, "
                f"real tool requires {sorted(real_required)}"
            )
    assert not drift, "stub required-args drifted from the registry:\n  " + "\n  ".join(drift)


