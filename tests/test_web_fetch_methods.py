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

from arelis.tools import policy
from arelis.tools.confirm_copy import confirm_headline
from arelis.tools.fetch import (
    BlockedUrlError,
    HeaderError,
    guarded_request,
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


async def test_a_post_reaches_the_server_with_its_body(wired, resolvable):
    rec = wired(_Recorder())
    result = await _tool().run(
        url="https://api.example.com/v1/items",
        method="POST",
        body='{"name": "widget"}',
        headers={"Content-Type": "application/json"},
    )
    assert result.ok, result.output
    sent = rec.requests[0]
    assert sent.method == "POST"
    assert sent.content == b'{"name": "widget"}'
    assert sent.headers["content-type"] == "application/json"


async def test_an_auth_header_is_actually_sent(wired, resolvable):
    rec = wired(_Recorder())
    await _tool().run(
        url="https://api.example.com/me",
        headers={"Authorization": "Bearer test-token"},
    )
    assert rec.requests[0].headers["authorization"] == "Bearer test-token"


async def test_headers_as_a_json_string_still_work(wired, resolvable):
    """Small models emit object params as strings. Refusing costs a round."""
    rec = wired(_Recorder())
    await _tool().run(
        url="https://api.example.com/me",
        headers='{"X-Key": "abc"}',
    )
    assert rec.requests[0].headers["x-key"] == "abc"


async def test_delete_and_patch_are_available(wired, resolvable):
    rec = wired(_Recorder())
    await _tool().run(url="https://api.example.com/items/1", method="DELETE")
    await _tool().run(url="https://api.example.com/items/1", method="PATCH", body="{}")
    assert [r.method for r in rec.requests] == ["DELETE", "PATCH"]


async def test_a_plain_get_is_unchanged(wired, resolvable):
    rec = wired(_Recorder(lambda r: httpx.Response(200, text="hello")))
    result = await _tool().run(url="https://example.com/x")
    assert result.ok
    assert rec.requests[0].method == "GET"
    assert "hello" in result.output


# --- the gate ---------------------------------------------------------------


def test_a_get_is_still_a_read():
    assert not policy.action_is_write("web_fetch", {"url": "https://x/"})
    assert not policy.action_is_write("web_fetch", {"url": "https://x/", "method": "GET"})
    assert policy.confirm_toggle("web_fetch", {"url": "https://x/"}) == "none"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post", "Delete"])
def test_every_other_method_is_a_write(method):
    args = {"url": "https://x/", "method": method}
    assert policy.action_is_write("web_fetch", args)
    assert policy.confirm_toggle("web_fetch", args) == "writes"


def test_a_delete_is_destructive_so_the_voice_face_still_pauses():
    """Filament grants on a spoken ask and only pauses for destructive calls.

    Without this, "delete my account" over voice would go through with no
    pause at all.
    """
    args = {"url": "https://api.example.com/account", "method": "DELETE"}
    assert policy.action_is_destructive("web_fetch", args)
    assert policy.always_pause("web_fetch", args)


def test_a_post_is_not_destructive():
    """Writes ask on the card face; only deletes interrupt a spoken grant."""
    args = {"url": "https://x/", "method": "POST"}
    assert not policy.action_is_destructive("web_fetch", args)


def test_the_card_names_the_host_and_the_verb():
    assert (
        confirm_headline(
            "web_fetch", {"url": "https://api.stripe.com/v1/charges", "method": "POST"}
        )
        == "post to api.stripe.com"
    )
    assert (
        confirm_headline("web_fetch", {"url": "https://api.x.com/u/1", "method": "DELETE"})
        == "delete from api.x.com"
    )


def test_the_card_does_not_print_the_key():
    """A card is one screenshot away from being somewhere it should not be."""
    line = confirm_headline(
        "web_fetch",
        {
            "url": "https://api.example.com/v1",
            "method": "POST",
            "headers": {"Authorization": "Bearer sk-live-super-secret"},
            "body": '{"password": "hunter2"}',
        },
    )
    assert "sk-live" not in line
    assert "hunter2" not in line


# --- the header guard -------------------------------------------------------


def test_host_cannot_be_overridden():
    """Every URL check in fetch.py validates the URL's host. A Host header
    that disagrees is how a checked request arrives somewhere else."""
    with pytest.raises(HeaderError) as exc:
        sanitize_headers({"Host": "169.254.169.254"})
    assert "Host" in str(exc.value)


@pytest.mark.parametrize(
    "name", ["Content-Length", "Transfer-Encoding", "Connection", "Proxy-Authorization"]
)
def test_the_framing_headers_are_refused(name):
    with pytest.raises(HeaderError):
        sanitize_headers({name: "1"})


def test_a_newline_in_a_value_is_refused():
    with pytest.raises(HeaderError):
        sanitize_headers({"X-A": "b\r\nX-Injected: yes"})


def test_a_newline_in_a_name_is_refused():
    with pytest.raises(HeaderError):
        sanitize_headers({"X-A\r\nX-B": "c"})


def test_an_ordinary_header_passes():
    assert sanitize_headers({"Authorization": "Bearer x", "Accept": "application/json"}) == {
        "Authorization": "Bearer x",
        "Accept": "application/json",
    }


async def test_a_forbidden_header_fails_the_call_rather_than_being_dropped(
    wired, resolvable
):
    """A dropped Authorization reads as "the API said no", which is a lie.

    `resolvable` matters here. Without it this test passed with the header
    guard disabled, because the made-up host failed DNS and `ok` was False for
    a reason that had nothing to do with headers.
    """
    rec = wired(_Recorder())
    result = await _tool().run(url="https://x.example/", headers={"Host": "evil"})
    assert not result.ok
    assert "Host" in result.output
    assert not rec.requests


# --- SSRF, on the new methods too -------------------------------------------


async def test_a_post_to_a_private_address_is_blocked(wired):
    rec = wired(_Recorder())
    result = await _tool().run(url="http://127.0.0.1:11434/api/generate", method="POST", body="{}")
    assert not result.ok
    assert not rec.requests, "the request must not be made, not merely hidden"


async def test_a_post_does_not_follow_a_redirect(wired, resolvable):
    """A 307 replays the method, body and Authorization against a host the
    server picked. There is no check that makes that safe."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "start" in str(request.url):
            return httpx.Response(307, headers={"location": "http://127.0.0.1:11434/x"})
        return httpx.Response(200, text="should never get here")

    rec = wired(_Recorder(handler))
    result = await _tool().run(url="https://start.example/", method="POST", body="secret")
    assert not result.ok
    assert "redirect" in result.output.lower()
    assert len(rec.requests) == 1


async def test_a_get_still_follows_redirects(wired, resolvable):
    """The hop-by-hop check makes this safe, and losing it would be a
    regression in ordinary reading."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "start" in str(request.url):
            return httpx.Response(302, headers={"location": "https://end.example/"})
        return httpx.Response(200, text="arrived")

    wired(_Recorder(handler))
    result = await _tool().run(url="https://start.example/")
    assert result.ok
    assert "arrived" in result.output


async def test_guarded_request_blocks_a_private_target_directly():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ) as client:
        with pytest.raises(BlockedUrlError):
            await guarded_request(client, "POST", "http://localhost:8080/x", content="{}")


# --- the mistakes a model makes ---------------------------------------------


async def test_an_unknown_method_says_which_ones_exist(wired):
    wired(_Recorder())
    result = await _tool().run(url="https://x.example/", method="FETCH")
    assert not result.ok
    assert "POST" in result.output


async def test_a_body_on_a_get_is_caught_rather_than_ignored(wired):
    """Servers drop a GET body silently, which looks like the API doing
    nothing at all."""
    rec = wired(_Recorder())
    result = await _tool().run(url="https://x.example/", body='{"a":1}')
    assert not result.ok
    assert "POST" in result.output
    assert not rec.requests


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
