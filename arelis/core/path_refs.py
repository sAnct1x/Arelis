"""The pieces every "did they mention a file?" regex is built from.

Two modules scan chat and tool notes for a path — `document_refs` for things
that can be opened or emailed, `image_refs` for things vision can look at. They
were written separately, and the difference between them was a bug rather than
a design:

`document_refs` grew a POSIX-absolute branch with a comment explaining why —
"Windows CI never sees this hole: tmp_path is C:\\... and the drive-letter
alternative matches. Ubuntu pytest writes /tmp/pytest-of-runner/... and the
note was dropped." `image_refs` never got that branch. So on any machine
without drive letters, `/tmp/x/arelis_1234.png` was not recognised as a path at
all, and `latest_generated_image_path` fell through to "newest file in
outputs/images" — which means she looks at *a different picture* than the one
that was named, and says nothing about the substitution.

Both also matched inside URLs. `https://example.com/documents/report.pdf`
produced the local path `documents/report.pdf`, and the image one produced
`s://example.com/outputs/images/cat.png`, having started the match at the `s`
in `https`.

The regexes stay separate — they look for different directories and different
suffixes, and merging them would mean one pattern with a suffix parameter,
which is harder to read than either. What is shared here is the answer to
"what does an absolute path look like, and where may one start", so that the
next fix lands in both.
"""

from __future__ import annotations

# What may appear inside a path. Quotes and angle brackets end it, because a
# path in chat is usually quoted or sits in a sentence.
PATH_CHARS = r"[^\s\"'<>|]"

# A leading `C:\` or `/`, refusing `//`. The `(?!/)` is what keeps `https://`
# out: the scheme's `s:` looks exactly like a drive letter, and the `:` `/` that
# follow it match too — the only thing that distinguishes them is the second
# slash. The lookbehind on the POSIX side stops a match starting midway through
# a URL path.
ABS_START = r"(?:[A-Za-z]:[\\/]|(?<![:/\w])/)(?!/)"

# An absolute directory prefix, or nothing — but "nothing" only in a position
# that is not already inside a path. Written as one alternation rather than an
# optional group because `(?:PREFIX)?` cannot express "if the prefix is absent,
# the match may not begin after a slash": the lookbehind would also apply after
# the prefix had been consumed, and `C:\Users\x\outputs\images\` ends in one.
ABS_PREFIX_OR_START = rf"(?:{ABS_START}{PATH_CHARS}+[/\\]|(?<![/\\\w]))"
