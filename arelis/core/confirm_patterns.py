"""The two shapes every send-or-create conversation ends in.

"Yes." and "Would you like me to send it?" — one from the user, one from the
assistant. SMS, email and agenda each wrote both out by hand, and the copies
did what copies do: they drifted in ways nobody chose and nobody could see.

The drift, measured before this module existed:

    utterance        sms  email  agenda
    "yes"             y     y      y
    "yes, please"     y     n      y
    "yes,"            n     n      y
    "okay,"           n     n      y
    "please"          y     n      y
    "ship it"         n     y      n
    "proceed"         n     n      y

The "ship it" and "proceed" rows are the *point* — those verb lists are domain
knowledge and they belong apart. Sending a text and creating a calendar event
are different acts, confirmed with different words. The rest of the table is
not domain knowledge. It is punctuation: email's trailing allowance was
``(?:\\s+please)?`` where SMS took ``(?:\\s*,?\\s*please)?`` and agenda took
``[,.]?\\s*(?:please)?``, so the most ordinary polite yes in the language
confirmed a text and a calendar event and did nothing whatever to an email.
Nothing decided that. It was the third time somebody typed out the same regex.

Splitting the affirmation from the command
------------------------------------------

Putting the three side by side turned up something none of them had right.
``_SEND_CONFIRM`` was doing two jobs at once:

- **"yes" / "ok" / "please"** carry no content. They could be answering any
  question in the conversation, or be a fragment Whisper found in room noise.
  These are only a grant if the assistant actually asked something.
- **"send the text" / "send it now"** name the act. Speech-to-text does not
  hallucinate a transitive verb and its object out of nothing, and there is no
  other question in the room they could be answering.

Both modules conflated the two and so both were wrong, in opposite
directions. Email required no offer for either, which is how a stale "yes"
revived a sendable draft. SMS required one for *both*, which meant that when
the model stalled and showed a draft without asking — "Ready when you are." —
a user saying "send the text" got nothing at all, over and over, with no
way to find out why.

So the halves are built separately here and the call sites combine them, which
is the only place the difference between "they consented" and "they instructed"
can be argued with.
"""

from __future__ import annotations

import re

# Bare agreement. On its own this is not permission to do anything; it is
# permission to do the thing that was just offered.
_AFFIRMATIONS = (
    "yes",
    "yep",
    "yeah",
    "ok",
    "okay",
    r"go\s+ahead",
    r"do\s+it",
)

# "yes, please" / "yes please" / "yes." / "yes," — one word of agreement with
# manners attached, and none of it changes what was agreed to.
_TRAILING_PLEASE = r"(?:\s*,?\s*please)?"
_TRAILING_PUNCT = r"\s*[,.!]?$"


def _whole_utterance(*alternatives: str) -> re.Pattern[str]:
    """Anchor at both ends, which is the safety property of this whole module.

    "Yes, and also text Robin that I am late" is a new turn with new content,
    not a grant for the draft sitting in history. A confirmation only counts
    when it is the entire thing the user said.
    """
    body = "|".join(alternatives)
    return re.compile(rf"(?i)^\s*(?:{body}){_TRAILING_PUNCT}")


def affirmation_pattern(*extra: str) -> re.Pattern[str]:
    """Match a content-free yes. Callers must gate this on a live offer.

    ``extra`` adds a channel's own way of agreeing — email takes "ship it",
    and SMS and agenda take a bare "please", which email never did.
    """
    return _whole_utterance("(?:" + "|".join([*_AFFIRMATIONS, *extra]) + ")" + _TRAILING_PLEASE)


def send_command_pattern(*verbs: str) -> re.Pattern[str]:
    """Match an explicit instruction to go. Self-contained; needs no offer.

    ``verbs`` are the channel's own ("send the text", "proceed with creating").
    """
    return _whole_utterance(*verbs)


def send_confirm_pattern(
    *verbs: str,
    affirmations: tuple[str, ...] = (),
) -> re.Pattern[str]:
    """Either half: a bare yes or an explicit command.

    This is the coarse gate the walks still open with, because both halves need
    a draft revived before anything can decide whether the user was consenting
    or instructing. The finer question is asked separately, with
    `send_command_pattern`.
    """
    return _whole_utterance(
        "(?:" + "|".join([*_AFFIRMATIONS, *affirmations]) + ")" + _TRAILING_PLEASE,
        *verbs,
    )


def proceed_ask_pattern(
    offer: str,
    gerund: str,
    *extra: str,
) -> re.Pattern[str]:
    """Match the assistant having just offered to do the thing.

    This is what makes a later bare "yes" mean something. Searched rather than
    anchored, because it arrives in the middle of a sentence the model wrote.

    ``offer`` is the verb as it appears after "to" / "shall I" ("send",
    "(?:proceed|create)"); ``gerund`` is the same verb after "proceed with".
    Agenda was missing "shall i proceed" from its own list while accepting
    "would you like me to proceed" — sharing the skeleton is what fixed that.
    """
    alternatives = [
        rf"would\s+you\s+like\s+(?:me\s+)?to\s+{offer}",
        rf"shall\s+i\s+{offer}",
        rf"want\s+me\s+to\s+{offer}",
        rf"proceed\s+with\s+{gerund}",
        *extra,
    ]
    return re.compile(r"(?i)\b(?:" + "|".join(alternatives) + r")\b")
