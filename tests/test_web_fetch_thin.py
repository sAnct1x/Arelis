"""A short page is not the same thing as an empty one.

Found 2026-09-17 while writing the first tests `html_text` ever had. The
comment on `_MIN_READABLE_CHARS` claimed 40 was "short enough that a real
one-sentence page still passes"; "The spring tide arrives at 06:14." is 33
characters, so it does not.

The threshold itself is defensible — it is aimed at "Loading…" and at a bare
`<div id="root">`, and lowering it starts reading shells as content. What was
not defensible was the branch behind it: `web_fetch` extracted the title and
the text, then returned a failure containing *neither*, so the model was told
"the page may require JavaScript" about a page it had successfully read. From
there it gives up or invents, which is complaint #1 in the audit.

The asymmetry made it plainer. A five-character `text/plain` body falls
through to the bottom of the same method and comes back verbatim with
ok=True. Only HTML got its content thrown away for being brief.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.tools.web import WebFetchTool


class _Response:
    def __init__(self, body: str, *, ctype: str = "text/html") -> None:
        self.status_code = 200
        self.text = body
        self.url = "https://example.test/page"
        self.headers = {"content-type": ctype}

    def raise_for_status(self) -> None:
        return None


@pytest.fixture()
def fetched(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point web_fetch at a literal body. No network in this file."""

    def _install(body: str, *, ctype: str = "text/html") -> None:
        import arelis.tools.web as web

        async def _fake_get(*args: Any, **kwargs: Any) -> _Response:
            return _Response(body, ctype=ctype)

        # guarded_request, not guarded_get: web_fetch grew a `method` and now
        # goes through the wrapper that decides whether redirects may be
        # followed. It still calls guarded_get underneath for a GET.
        monkeypatch.setattr(web, "guarded_request", _fake_get)

    return _install


_SHORT_PAGE = "<html><body><p>The spring tide arrives at 06:14.</p></body></html>"


@pytest.mark.asyncio
async def test_a_short_page_still_reports_what_it_read(fetched: Any) -> None:
    fetched(_SHORT_PAGE)
    result = await WebFetchTool("arelis-test/1.0").run(url="https://example.test/page")
    assert "The spring tide arrives at 06:14." in result.output, (
        "a page that was read successfully came back with its content dropped"
    )


@pytest.mark.asyncio
async def test_the_text_is_on_the_result_too(fetched: Any) -> None:
    """Not only in prose: a caller reading `data` should see it as well."""
    fetched(_SHORT_PAGE)
    result = await WebFetchTool("arelis-test/1.0").run(url="https://example.test/page")
    assert result.data.get("text") == "The spring tide arrives at 06:14."


@pytest.mark.asyncio
async def test_it_is_still_marked_as_a_weak_read(fetched: Any) -> None:
    """Reporting the text must not become a claim that the page is complete.

    Thin usually *does* mean a shell. The model needs the words and the
    warning, not one or the other.
    """
    fetched(_SHORT_PAGE)
    result = await WebFetchTool("arelis-test/1.0").run(url="https://example.test/page")
    assert result.ok is False
    assert "javascript" in result.output.lower()


@pytest.mark.asyncio
async def test_an_actually_empty_shell_reports_nothing_extra(fetched: Any) -> None:
    fetched("<html><body><div id='root'></div></body></html>")
    result = await WebFetchTool("arelis-test/1.0").run(url="https://example.test/page")
    assert result.ok is False
    assert "all that was readable" not in result.output.lower()


@pytest.mark.asyncio
async def test_a_secret_on_a_short_page_is_redacted(fetched: Any) -> None:
    """The successful path redacts; this one has to as well.

    Short does not mean harmless. An API key is shorter than a sentence, and
    a debug page that leaks one is exactly the kind of page that extracts to
    under forty characters.
    """
    fetched("<html><body>sk-abcdefghijklmnopqrstuvwxyz0123</body></html>")
    result = await WebFetchTool("arelis-test/1.0").run(url="https://example.test/page")
    assert "sk-abcdefghijklmnopqrstuvwxyz0123" not in result.output
    assert "sk-abcdefghijklmnopqrstuvwxyz0123" not in str(result.data)


@pytest.mark.asyncio
async def test_a_normal_page_is_unaffected(fetched: Any) -> None:
    fetched(
        "<html><head><title>Tides</title></head><body><p>The spring tide "
        "arrives at 06:14 tomorrow, about an hour later than today.</p>"
        "</body></html>"
    )
    result = await WebFetchTool("arelis-test/1.0").run(url="https://example.test/page")
    assert result.ok is True
    assert "Tides" in result.output
    assert "all that was readable" not in result.output.lower()
