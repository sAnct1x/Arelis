"""Two modules ask "did they mention a file?" and gave different answers.

`document_refs` and `image_refs` each grew their own path regex. The gap
between them was not a design choice — `document_refs` had a POSIX-absolute
branch with a comment explaining that Windows CI hides the hole, and
`image_refs` simply never got one.

The consequence is the worst kind, because nothing errors. `path_from_text`
returns None, `latest_generated_image_path` falls through to "newest file in
outputs/images", and she describes a different picture than the one that was
named without mentioning the substitution.
"""

from __future__ import annotations

import pytest

from arelis.core.document_refs import _PATH_MENTION as DOC
from arelis.core.image_refs import _PATH_MENTION as IMG
from arelis.core.image_refs import path_from_text


def _hit(pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


# --- the hole that only opens off Windows -----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "/tmp/pytest-of-runner/pytest-1/test_x0/arelis_1234.png",
        "/home/you/work/outputs/images/cat.png",
        "/var/folders/ab/T/data/drops/scan.jpg",
    ],
)
def test_a_posix_absolute_image_path_is_seen(text):
    """Every one of these returned None before, on any machine without drive
    letters, which is every machine in CI."""
    assert _hit(IMG, text) == text


def test_the_whole_absolute_path_is_captured_not_just_the_tail():
    """Returning `outputs/images/cat.png` from an absolute mention is worse
    than returning nothing: it resolves against the cwd, so it names a real
    file somewhere else or no file at all."""
    text = "/home/you/work/outputs/images/cat.png"
    assert _hit(IMG, text) == text


def test_the_document_side_still_sees_posix_paths():
    assert _hit(DOC, "/tmp/pytest-of-runner/pytest-1/report.pdf") == (
        "/tmp/pytest-of-runner/pytest-1/report.pdf"
    )


def test_windows_paths_did_not_regress():
    win_img = r"C:\Users\you\outputs\images\cat.png"
    win_doc = r"C:\Users\you\documents\report.pdf"
    assert _hit(IMG, win_img) == win_img
    assert _hit(DOC, win_doc) == win_doc


def test_a_plain_relative_mention_still_works():
    assert _hit(IMG, "saved to outputs/images/cat.png") == "outputs/images/cat.png"
    assert _hit(DOC, "wrote documents/report.pdf") == "documents/report.pdf"


# --- URLs are not local files -----------------------------------------------


def test_a_url_is_not_read_as_a_local_document():
    """This returned `documents/report.pdf`, so "open that" offered a card for
    a local file that was never written."""
    assert _hit(DOC, "it is at https://example.com/documents/report.pdf") is None


def test_a_url_is_not_read_as_a_local_image():
    """Worse than a false positive: the match started at the `s` in `https`,
    so the path handed to vision was `s://example.com/outputs/images/cat.png`."""
    assert _hit(IMG, "see https://example.com/outputs/images/cat.png") is None


def test_the_scheme_is_what_gets_rejected_not_the_word_https():
    """http:// and any other scheme, not a special case for one of them."""
    assert _hit(IMG, "ftp://host/outputs/images/x.png") is None
    assert _hit(IMG, "http://host/data/drops/x.png") is None


def test_a_bare_double_slash_is_refused():
    assert _hit(DOC, "//host/documents/report.pdf") is None


def test_a_path_after_a_word_is_not_a_path():
    """`myoutputs/images/x.png` is not `outputs/images/x.png`."""
    assert _hit(IMG, "myoutputs/images/x.png") is None


# --- the suffix sets stay separate ------------------------------------------


def test_the_image_pattern_ignores_documents():
    assert _hit(IMG, r"C:\Users\you\documents\report.pdf") is None


def test_the_document_pattern_covers_charts():
    """plot writes PNGs and they share the open / show-in-folder path."""
    assert _hit(DOC, r"C:\Users\you\outputs\plots\fit.png") is not None


# --- the caller, which is where the silence happened ------------------------


def test_path_from_text_returns_the_posix_path(tmp_path):
    text = "I saved it to /srv/data/drops/receipt.jpg for you"
    assert path_from_text(text) == "/srv/data/drops/receipt.jpg"


def test_path_from_text_is_quiet_about_a_url():
    assert path_from_text("grab https://example.com/outputs/images/a.png") is None


def test_trailing_punctuation_is_trimmed():
    assert path_from_text("saved to outputs/images/a.png.") == "outputs/images/a.png"
