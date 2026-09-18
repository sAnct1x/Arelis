"""The layering that item 3.5 existed to buy, and the door it had to leave open.

Two things can go wrong with a module that was carved out of another one, and
neither shows up in a test of what the functions return.

The first is that the carve-out is cosmetic. `intent_catalog.is_tiny_prompt_ask`
decides a turn needs no tools at all; to do that it wanted to know whether the
user had said hello, and it got that by importing the SMS draft reconstructor —
a thousand lines of recipient binding and STT repair, pulled in to recognise
"hey". Moving the guards to their own module fixes nothing if
`utterance_guards` then imports `sms_complete` itself, or if `intent_catalog`
keeps reaching for the old address. Neither is visible from the outside:
everything still returns the right answer, and the dependency is exactly where
it was. So the first test here reads `sys.modules` in a fresh interpreter,
because that is the only place the difference is observable.

The second is that the door gets shut on people who are not allowed to reopen
it. Fourteen modules and the test suite import these names *through*
`sms_complete`, and `orchestrator_shared` is one of them — a file this lane may
not edit. A re-export that quietly drops a name breaks a caller that cannot be
fixed from here, and it breaks it at import time, on a path that only runs when
someone is trying to send a text.

The behaviour tests at the end are for the guards that had no coverage anywhere
else. They are not a full suite for eighteen classifiers; they are the handful
whose mistakes would be silent.
"""

from __future__ import annotations

import subprocess
import sys

from arelis.core import sms_complete, utterance_guards

# Every name the extraction moved. `sms_complete` must keep answering to all of
# them, because callers this lane cannot edit ask it to.
MOVED = (
    "looks_like_browser_or_url",
    "looks_like_closing_chitchat",
    "looks_like_contact_email_ask",
    "looks_like_contact_phone_ask",
    "looks_like_contacts_followup",
    "looks_like_contacts_utterance",
    "looks_like_describe_followup",
    "looks_like_goals_utterance",
    "looks_like_greeting",
    "looks_like_image_edit",
    "looks_like_image_gen",
    "looks_like_look_or_file",
    "looks_like_math_ask",
    "looks_like_memory_utterance",
    "looks_like_tasks_utterance",
    "looks_like_workspace_write",
    "soften_caps",
)


def _modules_after(code: str) -> set[str]:
    """Which arelis modules are loaded once this snippet has run.

    A subprocess because the answer is only meaningful in an interpreter that
    has not already imported half the package — inside the test session,
    `sms_complete` is in `sys.modules` no matter what this module does.
    """
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys\n{code}\n"
            "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('arelis'))))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def test_the_guards_module_does_not_drag_in_the_module_it_left() -> None:
    loaded = _modules_after("import arelis.core.utterance_guards")
    assert "arelis.core.sms_complete" not in loaded, (
        "utterance_guards imports sms_complete, so the extraction moved text "
        "around without moving the dependency. Whatever needs sms_complete "
        "belongs back in it."
    )


def test_deciding_a_turn_needs_no_tools_no_longer_loads_the_sms_reconstructor() -> None:
    """The actual point of 3.5, and the only test that can see it.

    The guard import inside `is_tiny_prompt_ask` is deliberately lazy, so
    merely importing `intent_catalog` proves nothing either way — the old
    version would have passed that. This calls the function first, which is
    what forces whichever module it really depends on to load.
    """
    loaded = _modules_after(
        "from arelis.core.intent_catalog import is_tiny_prompt_ask\nis_tiny_prompt_ask('hey')"
    )
    assert "arelis.core.utterance_guards" in loaded, (
        "is_tiny_prompt_ask no longer reaches the guards at all; this test is "
        "measuring nothing. Check what it imports now."
    )
    assert "arelis.core.sms_complete" not in loaded, (
        "intent_catalog still reaches into sms_complete. is_tiny_prompt_ask "
        "runs on every turn; it should not need the draft reconstructor to "
        "recognise a greeting."
    )


def test_every_moved_guard_still_answers_at_its_old_address() -> None:
    missing = [name for name in MOVED if not hasattr(sms_complete, name)]
    assert not missing, (
        "These names moved to utterance_guards without a re-export. "
        "orchestrator_shared and thirteen other modules import them through "
        f"sms_complete and cannot be edited from this lane: {missing}"
    )


def test_the_old_address_and_the_new_one_are_the_same_function() -> None:
    """A re-export, not a second copy that can drift from the first."""
    for name in MOVED:
        assert getattr(sms_complete, name) is getattr(utterance_guards, name), (
            f"{name} is a different object on each module. Two implementations "
            "of the same guard is the problem 3.5 was meant to remove."
        )


def test_the_moved_guards_are_named_in_the_modules_public_list() -> None:
    """`__all__` is what a star-import and a linter go by."""
    exported = set(sms_complete.__all__)
    # `soften_caps` is a helper the guards share, not a guard.
    missing = [n for n in MOVED if n != "soften_caps" and n not in exported]
    assert not missing, f"re-exported but absent from __all__: {missing}"


def test_a_greeting_is_told_apart_from_something_that_merely_starts_politely() -> None:
    """`is_tiny_prompt_ask` strips the tool surface off a turn this returns True for.

    A false positive costs the user every tool on a real request, so the
    interesting cases are the ones that open with a greeting and then ask for
    something.
    """
    assert utterance_guards.looks_like_greeting("hey")
    assert utterance_guards.looks_like_greeting("Good morning!")
    assert not utterance_guards.looks_like_greeting("hey can you text Brian that I am running late")
    assert not utterance_guards.looks_like_greeting("hello, what is 19 times 4")


def test_a_url_is_never_mistaken_for_the_body_of_a_half_written_text() -> None:
    """This guard is the reason "open x.com" does not get sent to somebody.

    The mishears are load-bearing: Whisper renders "open x.com" as "OpenX.com"
    and as "open X dot com", and a pending SMS draft will take any stray turn
    as the body it is waiting for.
    """
    assert utterance_guards.looks_like_browser_or_url("open x.com")
    assert utterance_guards.looks_like_browser_or_url("OpenX.com")
    assert utterance_guards.looks_like_browser_or_url("https://example.com/thing")
    assert utterance_guards.looks_like_browser_or_url("go to github.com")
    assert not utterance_guards.looks_like_browser_or_url("running 10 minutes late")
    assert not utterance_guards.looks_like_browser_or_url("tell him I said no")


def test_shouted_speech_is_softened_so_the_math_guard_can_still_read_it() -> None:
    """Whisper hands back whole clauses in capitals, which broke `\\bwhat is\\b`.

    Sentence case, not lowercase: the first letter is left alone because the
    guards that consume this are matching words, and nothing downstream cares
    whether the sentence starts with a capital.
    """
    assert utterance_guards.soften_caps("WHAT IS 19 TIMES 4") == "What is 19 times 4"
    assert utterance_guards.soften_caps("what is 19 times 4") == "what is 19 times 4"
    assert utterance_guards.soften_caps("") == ""
    assert utterance_guards.looks_like_math_ask("WHAT IS 19 TIMES 4")


def test_the_contact_field_guards_choose_which_line_to_read_not_what_to_do() -> None:
    """Both of these are narrower than their names, and safely so.

    `looks_like_contact_email_ask` is `\\bemail\\b` and nothing else, so it is
    True of "email Brian about the report" — which reads like a bug and is
    not. Its only caller is the branch in `turn_execute` that runs *after* the
    contacts tool has already returned a card, where the question being asked
    is "which field did they want read aloud". It cannot route a compose,
    because by then the routing has happened.

    Worth pinning rather than fixing: tightening the regex would change
    behaviour on the one caller for no benefit, and the name is the part that
    is wrong. Pinned here so the next person to read it does not have to
    re-derive that.
    """
    assert utterance_guards.looks_like_contact_phone_ask("what is her phone number?")
    assert utterance_guards.looks_like_contact_phone_ask("what is my wifes phone number")
    assert not utterance_guards.looks_like_contact_phone_ask("Who is my wife in my contacts?")
    assert utterance_guards.looks_like_contact_email_ask("what is Brian's email")
    # The phone regex lists "email" as one of its own trigger words, so
    # "what is her email" matches it too. The only thing keeping the caller
    # from reading out a number when the user asked for an address is the
    # early return at the top of `looks_like_contact_phone_ask`. Remove that
    # and both guards fire, the phone branch is checked first, and the answer
    # is the wrong field.
    assert utterance_guards.looks_like_contact_email_ask("what is her email")
    assert not utterance_guards.looks_like_contact_phone_ask("what is her email"), (
        "Both field guards fired. The caller checks phone first, so asking "
        "for an email address gets you a phone number read aloud."
    )
    assert not utterance_guards.looks_like_contact_phone_ask("what is my wifes email")
    # The two are mutually exclusive by construction, and the tie-break runs
    # both ways: naming "phone" takes the email guard out, and the phone guard
    # then wins, so a turn asking for both reads the number. The caller picks
    # one field to speak, so exactly one of these must ever be True.
    assert not utterance_guards.looks_like_contact_email_ask("what is Brian's phone")
    assert utterance_guards.looks_like_contact_phone_ask("what is Brian's phone and email")
    assert not utterance_guards.looks_like_contact_email_ask("what is Brian's phone and email")
    # The documented false positive. If this ever flips, the caller's context
    # gate is what to check before celebrating.
    assert utterance_guards.looks_like_contact_email_ask("email Brian about the report")
