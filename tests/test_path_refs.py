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

from arelis.core.document_refs import _PATH_MENTION as DOC
from arelis.core.image_refs import _PATH_MENTION as IMG


def _hit(pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


# --- the hole that only opens off Windows -----------------------------------


def test_the_whole_absolute_path_is_captured_not_just_the_tail():
    """Returning `outputs/images/cat.png` from an absolute mention is worse
    than returning nothing: it resolves against the cwd, so it names a real
    file somewhere else or no file at all."""
    text = "/home/you/work/outputs/images/cat.png"
    assert _hit(IMG, text) == text


def test_windows_paths_did_not_regress():
    win_img = r"C:\Users\you\outputs\images\cat.png"
    win_doc = r"C:\Users\you\documents\report.pdf"
    assert _hit(IMG, win_img) == win_img
    assert _hit(DOC, win_doc) == win_doc


def test_a_plain_relative_mention_still_works():
    assert _hit(IMG, "saved to outputs/images/cat.png") == "outputs/images/cat.png"
    assert _hit(DOC, "wrote documents/report.pdf") == "documents/report.pdf"


# --- URLs are not local files -----------------------------------------------


def test_the_scheme_is_what_gets_rejected_not_the_word_https():
    """http:// and any other scheme, not a special case for one of them."""
    assert _hit(IMG, "ftp://host/outputs/images/x.png") is None
    assert _hit(IMG, "http://host/data/drops/x.png") is None


def test_a_bare_double_slash_is_refused():
    assert _hit(DOC, "//host/documents/report.pdf") is None


# --- the suffix sets stay separate ------------------------------------------


# --- the caller, which is where the silence happened ------------------------


