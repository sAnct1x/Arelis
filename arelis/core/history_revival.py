"""When a bare "yes" is allowed to mean the draft from two turns ago.

Every send-or-create channel needs this, because the useful conversation is:

    user       text Robin that I am running late
    assistant  Would you like me to send it?
    user       yes

"yes" carries no recipient and no body. The draft has to come back out of
history or the feature does not exist. The danger is the other conversation,
which looks almost identical from the inside:

    user       email Robin about the report, body: numbers are attached
    assistant  Here is a draft.
    user       actually never mind, what is the weather
    assistant  It is raining in your area.
    user       yes

Nothing here grants anything. That "yes" is answering some other question, or
Whisper found it in room noise. But the draft is still back there, still
complete, and a walk that only asks "is there a finished draft in history?"
will find it and hand it to the force gate.

The thing that tells the two apart is not whether the assistant offered — it
is whether the user has *moved on*. A user turn that is not about the draft is
a new subject, and everything before it is over. That one rule is what the
three modules were each trying to express, and all three expressed it
differently:

    walk       non-offer assistant turn   unrelated user turn   reach
    sms        stop                       stop                  1 turn
    agenda     skip                       stop                  bounded
    email      skip                       *skip*                unbounded

Email was the outlier and the only unsafe one. It had no stop condition at
all: its first pass `continue`d over every user turn that did not parse as
mail, so a confirmation reached backwards without limit. Measured before this
module existed, with the draft five unrelated exchanges back, "yes" returned
it — complete, addressed, and ready for the Allow card to describe correctly.
Email is the worst channel to get this wrong in: a text goes to a number the
user has texted before, an email goes into a stranger's permanent archive.

SMS is stricter than this walk and stays on its own. It stops on *any*
non-offer turn, and it has two things this does not model — a second return
for a recipient-only draft, and a walk for a bare phone number arriving as the
address. Flattening those into a shared helper would have meant four callbacks
and a sentinel value, in the code that decides what text messages get sent.
It is left alone deliberately; see the note in `complete_sms_draft`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

Draft = TypeVar("Draft")


def last_draft_before_confirm(
    pairs: list[tuple[str, str]],
    *,
    parse: Callable[[str], Draft | None],
    accept: Callable[[Draft], bool],
    asked: Callable[[str], bool] | None = None,
) -> Draft | None:
    """The draft this confirmation is about, or None if the user has moved on.

    `pairs` is history *without* the current turn. The caller has already
    matched the confirmation against it, so including it would find the "yes",
    fail to parse it, and stop on iteration one — which is exactly the bug
    that kept the agenda revival from ever running in a live session.

    Walking backwards:

    - assistant turns are skipped, but an `asked` match latches the fact that
      an offer was made. That latch is what buys the walk permission to keep
      going past a user turn it cannot parse: once the assistant has asked a
      question, a short user reply is plausibly an answer to it rather than a
      change of subject.
    - a user turn that parses and passes `accept` is the answer.
    - any other user turn ends it. With no offer latched, the safe reading of
      an unparseable user turn is that the user is talking about something
      else, and consent does not carry across that.

    `accept` is separate from `parse` because "is this a draft" and "is this
    draft the one worth reviving" are different questions — email wants only
    complete composes here and has a second pass for the rest, agenda will
    take anything with a start time.

    Returning None is not a refusal to help. It drops the turn back to the
    ordinary path, where the model answers "yes" as conversation rather than
    as a send.
    """
    saw_ask = False
    for role, content in reversed(pairs):
        if role == "assistant":
            if asked is not None and asked(content or ""):
                saw_ask = True
            continue
        if role != "user":
            continue
        found = parse(content or "")
        if found is not None and accept(found):
            return found
        if saw_ask:
            continue
        return None
    return None
