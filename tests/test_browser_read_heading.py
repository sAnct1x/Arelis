"""Does a browser read label the h1 when that h1 is also the page title?

The logged preview for example.com showed title and url, then body text, and
no heading line. This drives the real read path with that HTML. It fails only
when the labelled heading line is missing.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from arelis.browser.actions import PlaywrightDriver, format_tab_read

_HTML = """<!doctype html>
<html>
<head><title>Example Domain</title></head>
<body>
<div>
<h1>Example Domain</h1>
<p>This domain is for use in documentation examples.</p>
</div>
</body>
</html>
"""
_URL = "https://example.com/"


class _HtmlPage:
    """Enough of a Playwright page to run PlaywrightDriver.read on fixture HTML."""

    def __init__(self, html: str, url: str) -> None:
        self.url = url
        self._html = html

    def set_default_timeout(self, _ms: int) -> None:
        return None

    def set_default_navigation_timeout(self, _ms: int) -> None:
        return None

    async def title(self) -> str:
        soup = BeautifulSoup(self._html, "html.parser")
        node = soup.title
        return str(node.string or "").strip() if node is not None else ""

    async def evaluate(self, script: str) -> dict[str, str]:
        soup = BeautifulSoup(self._html, "html.parser")
        # The read script asks for the h1. If it stops asking, the heading
        # field stays empty and the labelled line is gone.
        heading = ""
        if "querySelector('h1')" in script or 'querySelector("h1")' in script:
            node = soup.find("h1")
            if node is not None:
                heading = " ".join(node.get_text().split())[:160]
        body = soup.body
        text = body.get_text("\n") if body is not None else ""
        title_node = soup.title
        title = str(title_node.string or "").strip() if title_node is not None else ""
        return {"title": title, "url": self.url, "heading": heading, "text": text}


def _heading_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("heading:"):
            return line
    return ""


def test_format_tab_read_labels_an_h1_that_equals_the_title() -> None:
    text = format_tab_read(
        title="Example Domain",
        url=_URL,
        heading="Example Domain",
        body="This domain is for use in documentation examples.",
    )
    assert _heading_line(text) == "heading: Example Domain"


@pytest.mark.asyncio
async def test_page_read_labels_an_h1_that_equals_the_title() -> None:
    driver = PlaywrightDriver()
    driver._page = _HtmlPage(_HTML, _URL)
    result = await driver.read()
    assert result.ok, result.output
    assert _heading_line(result.output) == "heading: Example Domain"
    assert result.data is not None
    assert result.data.get("heading") == "Example Domain"
