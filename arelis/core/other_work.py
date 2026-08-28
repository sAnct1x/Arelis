"""This turn is about something other than composing a message.

Four places used to each keep a list of "don't revive a pending SMS/email
draft for this". The lists drifted. A calendar-open turn skipped the draft in
the agent loop and still revived it inside ``complete_sms_draft`` Case B,
because that copy had never learned ``looks_like_calendar_open``. A weather
turn skipped the email draft in the loop and not in ``complete_email_draft``.

One function, the union of every list. Callers keep their own exceptions
(an explicit "text Sam:" still wins; so does a compose-email verb).
"""

from __future__ import annotations

from arelis.attachments import (
    attachment_kinds_from_turn,
    split_attachments_turn,
    wants_image_edit,
)
from arelis.core.agenda_complete import (
    looks_like_calendar_close,
    looks_like_calendar_create,
    looks_like_calendar_delete,
    looks_like_calendar_open,
    looks_like_calendar_read,
)
from arelis.core.claims import (
    detect_analyze_ask,
    detect_cas_ask,
    detect_catalog_ask,
    detect_diagnostics_ask,
    detect_math_ask,
    detect_plot_ask,
)
from arelis.core.intent_catalog import WEATHER
from arelis.core.tile_complete import match_tile_intent


def looks_like_other_work(
    text: str,
    history: list | None = None,
) -> bool:
    """True when this turn is clearly not a request to compose SMS or email."""
    # sms_complete and email_complete call this, so those two families stay
    # deferred. Pulling them to the top would be a cycle, which is the mesh
    # this function exists to shrink rather than grow.
    from arelis.core.email_complete import (
        looks_like_mailbox_mutate,
        looks_like_schedule_manage,
        looks_like_scheduled_send,
    )
    from arelis.core.preflight import looks_like_room_create
    from arelis.core.sms_complete import (
        looks_like_browser_or_url,
        looks_like_goals_utterance,
        looks_like_image_gen,
        looks_like_stale_sms_skip,
        looks_like_tasks_utterance,
        looks_like_workspace_write,
    )

    raw = text or ""
    if not raw.strip():
        return False
    ask = split_attachments_turn(raw)[1] or raw
    return bool(
        looks_like_stale_sms_skip(raw, history or [])
        or looks_like_calendar_create(raw)
        or looks_like_calendar_delete(raw)
        or looks_like_calendar_close(raw)
        or looks_like_calendar_open(raw)
        or looks_like_calendar_read(raw)
        or match_tile_intent(raw)
        or detect_analyze_ask(raw)
        or detect_catalog_ask(raw)
        or detect_plot_ask(raw)
        or detect_math_ask(raw)
        or detect_cas_ask(raw)
        or detect_diagnostics_ask(raw)
        or "```" in raw
        or wants_image_edit(ask)
        or looks_like_image_gen(raw)
        or looks_like_scheduled_send(raw)
        or looks_like_schedule_manage(raw)
        or looks_like_mailbox_mutate(raw)
        or looks_like_workspace_write(raw)
        or looks_like_tasks_utterance(raw)
        or looks_like_goals_utterance(raw)
        or looks_like_browser_or_url(raw)
        or looks_like_room_create(raw)
        or WEATHER.matches(raw)
        or "image" in attachment_kinds_from_turn(raw)
    )
