"""What a fetched page turns into before she reads it.

The last of three tools no test file named (2026-09-17), and the one closest
to the complaint at the top of the audit. These five functions decide whether
a page counts as readable at all. Get `thin_readable` or `looks_like_css`
wrong and a page that fetched perfectly well is reported as empty -- or worse,
a stylesheet is handed over as prose and summarised as though it said
something. Neither failure announces itself; both end in a confident answer
built on nothing.

There is no network here. Every input is a literal page body, which is the
point: these are pure functions, and the reason they were never tested is
probably that the tools around them need a real fetch.
"""

from __future__ import annotations

from arelis.tools.html_text import (
    extract_text,
    looks_like_html,
)

_PAGE = """
<!doctype html>
<html>
  <head>
    <title>  Tide tables  </title>
    <style>body { color: red; }</style>
    <script>window.analytics = 1;</script>
  </head>
  <body>
    <h1>High water</h1>
    <p>The spring tide arrives at 06:14.</p>
    <noscript>Enable JavaScript.</noscript>
  </body>
</html>
"""


# --------------------------------------------------------------------------
# extract_text
# --------------------------------------------------------------------------


def test_words_do_not_get_welded_together() -> None:
    """Without a separator, adjacent tags run into one another.

    "High waterThe spring tide" is not a word anyone searches for, and it is
    the sort of damage that survives all the way into a summary.
    """
    _, text = extract_text("<p>High water</p><p>The spring tide</p>")
    assert "waterThe" not in text
    assert "High water The spring tide" == text


def test_a_page_with_no_title_is_not_an_error() -> None:
    title, text = extract_text("<html><body><p>hello</p></body></html>")
    assert title == ""
    assert text == "hello"


# --------------------------------------------------------------------------
# content_type_main
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# looks_like_html
# --------------------------------------------------------------------------


def test_html_is_recognised_without_a_header() -> None:
    """Plenty of servers send text/plain for a page. Sniff the body."""
    assert looks_like_html("<!DOCTYPE html><html><body>x", "")
    assert looks_like_html("\n\n  <html><body>x", "text/plain")
    assert looks_like_html("<div><body>late</body></div>", "")


# --------------------------------------------------------------------------
# looks_like_css -- the one that stops a stylesheet being summarised
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# thin_readable -- the empty-JS-shell detector
# --------------------------------------------------------------------------


