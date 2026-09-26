""" "No new messages" was being said when nothing could have been heard.

The user named SMS as their worst-behaving feature, and specifically "the
mobile side, because of our approach". The approach is: the phone is the
radio, and inbound arrives through a notification listener on Google
Messages. That listener is the only path that sees RCS, and it is also the
one Doze, a muted conversation, or battery optimisation can stop dead without
surfacing an error anywhere. On the companion path there is no PC-side
fallback either — `AndroidSmsProvider.supports_inbox_poll` returns False
unless an SMSGate inbox URL is configured as well.

So the ring buffer being empty has two meanings: nobody texted, or we are
deaf. `inbound_sms` answered both with "No inbound texts recorded this
session", `ok=True`, `count: 0`. Asked "did Robin text back?", the model reads
that as a clean no and says so — a confident wrong answer about somebody's
messages, which is complaint #1 arriving inside the feature named in
complaint #4.

Nothing here can prove the listener is alive; it only posts when a message
arrives. What it can prove is weaker and sufficient: whether the phone has
reached this machine at all. If it never has, inbound is certainly dark, and
the honest answer is "I cannot tell" rather than "no".
"""

from __future__ import annotations

import time

import pytest

from arelis.sms_inbound import InboundSms
from arelis.sms_ingest import COMPANION_PRESENCE, RECENT_INBOUND
from arelis.tools.inbound_sms import InboundSmsTool


@pytest.fixture(autouse=True)
def _clean_state():
    """Both stores are process-wide, so leakage between tests is real."""
    COMPANION_PRESENCE.reset()
    RECENT_INBOUND._items.clear()
    yield
    COMPANION_PRESENCE.reset()
    RECENT_INBOUND._items.clear()


def _arrive(body: str = "on my way", sender: str = "+15550001111") -> None:
    RECENT_INBOUND.record(
        InboundSms(id="m1", sender=sender, body=body, time="2026-09-17T23:00:00Z"),
        source="notification",
    )


# --------------------------------------------------------------------------
# The defect
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silence_from_a_phone_we_never_heard_is_not_a_no() -> None:
    result = await InboundSmsTool().run()

    assert result.ok is False, "an unknowable answer was reported as a clean result"
    assert "cannot tell" in result.output.lower()
    assert result.data["bridge"] == "unknown"


@pytest.mark.asyncio
async def test_the_model_is_told_not_to_turn_it_into_a_no() -> None:
    """The refusal has to survive summarising. Left to itself a model
    compresses "I could not check" into "nothing arrived", which is the exact
    sentence this test exists to prevent."""
    result = await InboundSmsTool().run()
    assert "no new messages" in result.output.lower()
    assert "do not report" in result.output.lower()


@pytest.mark.asyncio
async def test_the_answer_says_how_to_fix_it() -> None:
    """The three real causes, named, because "it might be broken" sends the
    user nowhere."""
    lowered = (await InboundSmsTool().run()).output.lower()
    assert "notification" in lowered
    assert "battery" in lowered
    assert "network" in lowered


# --------------------------------------------------------------------------
# And a genuine quiet spell still reads as quiet
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_live_bridge_with_no_texts_is_an_honest_no() -> None:
    COMPANION_PRESENCE.touch("/mobile/status")
    result = await InboundSmsTool().run()

    assert result.ok is True
    assert "no inbound texts" in result.output.lower()
    assert result.data["bridge"] == "seen"


@pytest.mark.asyncio
async def test_even_a_live_bridge_keeps_the_caveat() -> None:
    """A checked-in phone still proves nothing about the listener — a muted
    thread drops messages while the companion answers polls normally."""
    COMPANION_PRESENCE.touch("/mobile/status")
    lowered = (await InboundSmsTool().run()).output.lower()
    assert "muted" in lowered or "doze" in lowered


@pytest.mark.asyncio
async def test_a_stale_bridge_says_how_stale() -> None:
    """ "Checked in three hours ago" is a different answer from "moments ago",
    and the user is the one who can judge which matters."""
    COMPANION_PRESENCE.touch("/mobile/status")
    COMPANION_PRESENCE._last = time.time() - (3 * 3600)
    output = (await InboundSmsTool().run()).output
    assert "3 hours" in output


@pytest.mark.asyncio
async def test_messages_are_still_listed_normally() -> None:
    COMPANION_PRESENCE.touch("/inbound/sms")
    _arrive("running late")
    result = await InboundSmsTool().run()

    assert result.ok is True
    assert "running late" in result.output
    assert result.data["count"] == 1
    assert result.data["bridge"] == "seen"


@pytest.mark.asyncio
async def test_messages_arriving_without_a_recorded_touch_still_list() -> None:
    """The SMSGate fallback path does not go through the ingest handler, so it
    never touches presence. Texts it delivered must not be hidden behind a
    bridge warning — they are proof enough on their own."""
    _arrive("from the polling path")
    result = await InboundSmsTool().run()

    assert result.ok is True
    assert "from the polling path" in result.output


# --------------------------------------------------------------------------
# The presence record itself
# --------------------------------------------------------------------------


def test_presence_starts_unknown() -> None:
    assert COMPANION_PRESENCE.age_seconds() is None
    assert "has not contacted" in COMPANION_PRESENCE.describe()


def test_a_touch_is_recent() -> None:
    COMPANION_PRESENCE.touch("/mobile/sync")
    age = COMPANION_PRESENCE.age_seconds()
    assert age is not None and age < 5
    assert "moments ago" in COMPANION_PRESENCE.describe()


@pytest.mark.asyncio
async def test_a_real_request_through_the_server_records_presence(
    tmp_path,
) -> None:
    """End-to-end, because calling touch() by hand proves only that touch()
    works. What matters is that the live handler reaches it, and that a
    request with the wrong token does not — anyone on the LAN can knock, and
    a stranger's knock is not evidence the phone is there.
    """
    import asyncio
    import socket

    import httpx

    from arelis.core.bus import EventBus
    from arelis.sms_inbound import SeenMessageStore
    from arelis.sms_ingest import InboundIngestServer

    bus = EventBus()
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.start()
    try:
        assert COMPANION_PRESENCE.age_seconds() is None

        async with httpx.AsyncClient() as client:
            refused = await client.get(f"http://127.0.0.1:{port}/inbound/ping")
            assert refused.status_code == 401
        assert COMPANION_PRESENCE.age_seconds() is None, (
            "an unauthenticated knock was treated as the phone checking in"
        )

        async with httpx.AsyncClient() as client:
            ok = await client.get(
                f"http://127.0.0.1:{port}/inbound/ping",
                headers={"X-Arelis-Token": "test-token"},
            )
            assert ok.status_code == 200
        age = COMPANION_PRESENCE.age_seconds()
        assert age is not None and age < 5

        result = await InboundSmsTool().run()
        assert result.ok is True
        assert result.data["bridge"] == "seen"
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_minutes_and_hours_are_both_readable() -> None:
    COMPANION_PRESENCE.touch("/mobile/status")
    COMPANION_PRESENCE._last = time.time() - (20 * 60)
    assert "20 minutes" in COMPANION_PRESENCE.describe()
    COMPANION_PRESENCE._last = time.time() - (5 * 3600)
    assert "5 hours" in COMPANION_PRESENCE.describe()
