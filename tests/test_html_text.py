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
    content_type_main,
    extract_text,
    looks_like_css,
    looks_like_html,
    thin_readable,
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


def test_the_title_comes_back_trimmed() -> None:
    title, _ = extract_text(_PAGE)
    assert title == "Tide tables"


def test_the_prose_comes_back_and_the_machinery_does_not() -> None:
    _, text = extract_text(_PAGE)
    assert "The spring tide arrives at 06:14." in text
    assert "analytics" not in text, "a script body was read as page prose"
    assert "color: red" not in text, "a stylesheet was read as page prose"
    assert "Enable JavaScript" not in text


def test_words_do_not_get_welded_together() -> None:
    """Without a separator, adjacent tags run into one another.

    "High waterThe spring tide" is not a word anyone searches for, and it is
    the sort of damage that survives all the way into a summary.
    """
    _, text = extract_text("<p>High water</p><p>The spring tide</p>")
    assert "waterThe" not in text
    assert "High water The spring tide" == text


def test_whitespace_is_collapsed() -> None:
    _, text = extract_text("<p>a\n\n   b\t\tc</p>")
    assert text == "a b c"


def test_a_page_with_no_title_is_not_an_error() -> None:
    title, text = extract_text("<html><body><p>hello</p></body></html>")
    assert title == ""
    assert text == "hello"


def test_an_empty_title_tag_is_not_an_error() -> None:
    title, _ = extract_text("<html><head><title></title></head><body>x</body></html>")
    assert title == ""


def test_junk_does_not_raise() -> None:
    """A parse error mid-fetch should be an empty read, not a traceback."""
    for junk in ("", "not html at all", "<<<>>>", "<p>unclosed"):
        title, text = extract_text(junk)
        assert isinstance(title, str) and isinstance(text, str)


# --------------------------------------------------------------------------
# content_type_main
# --------------------------------------------------------------------------


def test_the_media_type_is_split_off_the_charset() -> None:
    assert content_type_main({"content-type": "text/html; charset=utf-8"}) == "text/html"


def test_the_header_name_is_matched_either_way_round() -> None:
    """requests lowercases its headers; a raw dict from anywhere else may not."""
    assert content_type_main({"Content-Type": "TEXT/HTML"}) == "text/html"


def test_a_missing_header_is_empty_not_a_crash() -> None:
    assert content_type_main({}) == ""
    assert content_type_main(object()) == ""


# --------------------------------------------------------------------------
# looks_like_html
# --------------------------------------------------------------------------


def test_the_declared_type_is_believed() -> None:
    assert looks_like_html("", "text/html")
    assert looks_like_html("", "application/xhtml+xml")


def test_html_is_recognised_without_a_header() -> None:
    """Plenty of servers send text/plain for a page. Sniff the body."""
    assert looks_like_html("<!DOCTYPE html><html><body>x", "")
    assert looks_like_html("\n\n  <html><body>x", "text/plain")
    assert looks_like_html("<div><body>late</body></div>", "")


def test_plain_text_is_not_mistaken_for_a_page() -> None:
    assert not looks_like_html("The spring tide arrives at 06:14.", "text/plain")
    assert not looks_like_html('{"tide": "06:14"}', "application/json")


# --------------------------------------------------------------------------
# looks_like_css -- the one that stops a stylesheet being summarised
# --------------------------------------------------------------------------


def test_a_declared_stylesheet_is_css() -> None:
    assert looks_like_css("", "text/css")


def test_a_stylesheet_with_no_content_type_is_still_css() -> None:
    body = "a { color: red; }\nb { color: blue; }\nc { color: green; }"
    assert looks_like_css(body, "")


def test_a_webfont_stylesheet_is_css() -> None:
    assert looks_like_css("@font-face { src: url(x.woff2); }", "")
    assert looks_like_css("@import url('other.css');", "")


def test_a_page_full_of_braces_is_not_css() -> None:
    """HTML wins the tie. A page with an inline <style> has plenty of braces,
    and calling it a stylesheet would throw away the article around it."""
    page = "<!doctype html><html><style>a{}b{}c{}</style><body>Real words here."
    assert not looks_like_css(page, "")
    assert not looks_like_css(page, "text/html")


def test_prose_about_code_is_not_css() -> None:
    assert not looks_like_css("Use { and } to open a block.", "text/plain")


# --------------------------------------------------------------------------
# thin_readable -- the empty-JS-shell detector
# --------------------------------------------------------------------------


def test_an_empty_shell_reads_as_thin() -> None:
    _, text = extract_text("<html><body><div id='root'></div></body></html>")
    assert thin_readable(text)


def test_a_normal_paragraph_does_not_read_as_thin() -> None:
    _, text = extract_text(
        "<html><body><p>The spring tide arrives at 06:14 tomorrow morning, "
        "about an hour later than today.</p></body></html>"
    )
    assert not thin_readable(text)


def test_a_short_real_sentence_reads_as_thin_and_that_is_a_known_cost() -> None:
    """The source comment used to claim otherwise, and it was wrong.

    "The spring tide arrives at 06:14." is a complete page and 33 characters,
    so it trips a threshold written for "Loading…". The threshold stays where
    it is — moving it down starts admitting real shells — but the callers must
    not silently bin the text, which is what
    `test_web_fetch_thin.py` pins.
    """
    _, text = extract_text("<html><body><p>The spring tide arrives at 06:14.</p></body></html>")
    assert len(text) < 40
    assert thin_readable(text)


def test_whitespace_only_reads_as_thin() -> None:
    assert thin_readable("        \n\n\t  ")
    assert thin_readable("")
