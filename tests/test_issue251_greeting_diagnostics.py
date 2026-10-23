"""#251: a test-session opener must not ship the missing-diagnostics refuse.

The 0.3.2 hand test said 'good evening, we are going to run some tests' and
got the canned exactness line. That opener is not a request to run her
suite. Dropping suite phrasing from exactness let 'run the tests' invent a
pass count again, so both halves live here.
"""

from __future__ import annotations

import pytest

from arelis.core.claims import detect_exactness_need, unsupported_exactness_reply
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import _exactness_finish_refuse

pytestmark = pytest.mark.no_ui

_ASK = "good evening, we are going to run some tests"
_REPLY = "Good evening. Ready when you are."
_SUITE_ASK = "run the tests"
_FAKE_PASS = "All 1306 tests passed."


def _finish(ask: str, reply: str) -> str | None:
    return _exactness_finish_refuse(
        reply,
        exact_need=detect_exactness_need(ask),
        ledger=EvidenceLedger(),
        numeric_gate=True,
        evidence_gate=True,
    )


def test_a_test_session_opener_does_not_get_the_diagnostics_refuse() -> None:
    """A greeting that mentions upcoming tests is chat, not a suite warrant.

    An invented pass count on 'run the tests' still has to be refused.
    """
    need = detect_exactness_need(_ASK)
    assert "diagnostics" not in need.kinds
    assert not need.needs_diagnostics
    assert _finish(_ASK, _REPLY) is None

    suite_need = detect_exactness_need(_SUITE_ASK)
    assert "diagnostics" in suite_need.kinds
    assert suite_need.needs_diagnostics
    refuse = _finish(_SUITE_ASK, _FAKE_PASS)
    assert refuse == unsupported_exactness_reply(["diagnostics"])
