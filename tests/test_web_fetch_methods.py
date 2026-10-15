"""web_fetch beyond GET: does it work, and does it ask first?

Two questions, and the second matters more. A POST is not a read — it changes
something on a machine that is not ours and cannot be undone from here — so
every test about the confirm gate below is really a test that adding this
capability did not quietly widen what Arelis will do unasked.

The SSRF and header guards are checked by disabling them and watching a test
fail, not by reading the code and believing it.
"""

from __future__ import annotations

import httpx
import pytest

from arelis.tools.fetch import (
    HeaderError,
    sanitize_headers,
)
from arelis.tools.web import WebFetchTool

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Recorder:
    """Captures what actually went on the wire, which is the only thing that
    settles whether a header was sent or merely accepted."""

    def __init__(self, handler=None) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._handler is not None:
            return self._handler(request)
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def resolvable(monkeypatch):
    """Let the made-up hosts past the URL guard.

    `check_url_allowed` does a real DNS lookup, so `api.example.com` is refused
    here for a reason that has nothing to do with what is being tested. Applied
    only where the question is what went on the wire — the SSRF tests below run
    against the real guard, because stubbing it there would test the stub.
    """
    import arelis.tools.fetch as fetch_mod

    async def _allow(url: str, *, block_private: bool = True) -> str | None:
        return None

    monkeypatch.setattr(fetch_mod, "check_url_allowed", _allow)


@pytest.fixture
def wired(monkeypatch):
    """Point the tool's client at a transport we control."""

    def _wire(recorder: _Recorder):
        real_client = httpx.AsyncClient

        def _factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(recorder)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", _factory)
        return recorder

    return _wire


def _tool() -> WebFetchTool:
    return WebFetchTool("arelis-test/1.0", timeout_s=5)


# --- the capability that did not exist -------------------------------------


# --- the gate ---------------------------------------------------------------


# --- the header guard -------------------------------------------------------


@pytest.mark.parametrize(
    "name", ['Content-Length', 'Transfer-Encoding']
)
def test_the_framing_headers_are_refused(name):
    with pytest.raises(HeaderError):
        sanitize_headers({name: "1"})


# --- SSRF, on the new methods too -------------------------------------------


# --- the mistakes a model makes ---------------------------------------------


async def test_an_enormous_body_is_refused(wired, resolvable):
    rec = wired(_Recorder())
    result = await _tool().run(url="https://x.example/", method="POST", body="x" * 200_000)
    assert not result.ok
    assert "200000" in result.output.replace(",", "")
    assert not rec.requests


async def test_headers_that_are_not_an_object_are_refused(wired):
    wired(_Recorder())
    result = await _tool().run(url="https://x.example/", headers="not json at all")
    assert not result.ok
    assert "json" in result.output.lower()
