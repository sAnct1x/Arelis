"""#251: a test-session opener must not ship the missing-diagnostics refuse.

The 0.3.2 hand test said 'good evening, we are going to run some tests' and
got the canned exactness line. That opener is not a request to run her
suite. The finish gate used the same wide phrase match as preflight, so a
greeting reply was treated as a missing warrant.
"""

from __future__ import annotations

import pytest

from arelis.core.claims import detect_exactness_need
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import _exactness_finish_refuse

pytestmark = pytest.mark.no_ui

_ASK = "good evening, we are going to run some tests"
_REPLY = "Good evening. Ready when you are."


def test_a_test_session_opener_does_not_get_the_diagnostics_refuse() -> None:
    """A greeting that mentions upcoming tests is chat, not a suite warrant."""
    need = detect_exactness_need(_ASK)
    assert "diagnostics" not in need.kinds
    assert not need.needs_diagnostics
    refuse = _exactness_finish_refuse(
        _REPLY,
        exact_need=need,
        ledger=EvidenceLedger(),
        numeric_gate=True,
        evidence_gate=True,
    )
    assert refuse is None
