"""What the model picks, unaided, when the real tool schemas are on the table.

Everything else under ``arelis/eval`` scripts the tool call: 49 of the 59
foundation scenarios emit their own ``tool_calls``, so the script makes the choice
and the mechanisms built to correct a choice never get a turn. Measured on
2026-08-14, the whole board scored 59/59 with the tool subset, the skill cards,
intent preflight and four force gates each disabled — not because they are inert,
but because that board cannot see them.

This module holds the corpus that can. Each case is an utterance whose right
answer is not in dispute, paired with every tool that would be a defensible pick,
so a miss is a real miss rather than a difference of opinion. Running it needs a
live model, which is why the runner lives in ``scripts/audit_tool_choice.py``;
what lives here is the corpus itself, plus the coherence checks that keep it from
rotting quietly. A case naming a tool the registry no longer offers is a case that
can never pass, and that is the failure mode worth a test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChoiceCase:
    """One utterance and the tools that answer it.

    ``accepts`` is a set of defensible picks, not a single expected value. "Read
    the text in this screenshot" is ``ocr`` or ``vision`` depending on whether you
    read "text" as exact characters or as a description, and marking either wrong
    would measure our taste rather than the model's judgement.
    """

    utterance: str
    accepts: tuple[str, ...]
    note: str = ""

    def hit(self, tool: str) -> bool:
        return (tool or "").strip() in self.accepts


# Ordered roughly by how often the ask turns up in real use, so a truncated run
# still covers the everyday surface first.
CHOICE_CASES: tuple[ChoiceCase, ...] = (
    ChoiceCase("what is 17 times 19?", ("calculator",)),
    ChoiceCase("what's the weather going to be like tomorrow?", ("weather",)),
    ChoiceCase("send a text to my wife telling her I love her", ("send_sms",)),
    ChoiceCase("did my wife text me back?", ("inbound_sms",)),
    ChoiceCase("what's on my calendar today?", ("agenda",)),
    ChoiceCase("what are my goals?", ("goals",)),
    ChoiceCase("what do I have to do today?", ("tasks", "agenda")),
    ChoiceCase(
        "what needs my attention?",
        ("tasks", "goals", "agenda"),
        note="The attention tool that aggregated these was removed 2026-08-14.",
    ),
    ChoiceCase(
        "what's going on today?",
        ("agenda", "inbox", "tasks"),
        note="No single briefing tool any more; any of the three is a fair start.",
    ),
    ChoiceCase("do I have any unread email?", ("inbox",)),
    ChoiceCase("remember that I climb on Tuesdays", ("memory",)),
    ChoiceCase("what did I say about the Sherpa work last night?", ("recall",)),
    ChoiceCase("who is in my contacts?", ("contacts",)),
    ChoiceCase("what's my wife's phone number?", ("contacts",)),
    ChoiceCase("what changed in the repo since yesterday?", ("git_info",)),
    ChoiceCase(
        "read arelis/core/tool_subset.py and tell me what it does", ("workspace",)
    ),
    ChoiceCase("summarise the columns in data/sales.csv", ("analyze",)),
    ChoiceCase("pull the quotes out of docs/spec.pdf", ("doc_extract",)),
    ChoiceCase("what's on my clipboard?", ("clipboard",)),
    ChoiceCase("describe outputs/images/demo.png for me", ("vision",)),
    ChoiceCase("read the text in outputs/images/receipt.png", ("ocr", "vision")),
    ChoiceCase("generate an image of a lighthouse at dusk", ("image",)),
    ChoiceCase("open youtube for me", ("browser",)),
    ChoiceCase("who won the F1 race this weekend?", ("web_search",)),
    ChoiceCase("read https://example.com/article and summarise it", ("scrape",)),
    ChoiceCase(
        "do a deep dive on ROCm support for Zipformer",
        ("research_report", "web_search"),
    ),
    ChoiceCase("where do you think I am?", ("user_location",)),
    # The owner's own words for the multimodal asks. Before 2026-08-14 these
    # routed nowhere at all, and "analyze" is the name of the spreadsheet reader,
    # so the likely pick was a pandas tool answering "Unsupported file type".
    #
    # Each names a file, because in production they always do: a dropped or pasted
    # attachment arrives with a staged path and a rule naming the tool. Measured
    # pathless on 2026-08-14, the production arm answered in prose asking which
    # picture — which is right, and scored as a miss for the wrong reason. The bare
    # arm "hit" the same case by calling vision with a path it made up. What is
    # being measured here is the verb, not whether the model will guess a filename.
    ChoiceCase(
        "analyze the picture I just sent you: outputs/images/demo.png",
        ("vision",),
        note="analyze is the user's verb here, not the table tool.",
    ),
    ChoiceCase(
        "analyze the document I gave you: docs/spec.pdf",
        ("doc_extract",),
        note="Same verb, a document rather than an image.",
    ),
    ChoiceCase(
        "analyze this screenshot outputs/images/receipt.png",
        ("vision", "ocr"),
    ),
)


def case_tools() -> set[str]:
    """Every tool named as acceptable by any case."""
    out: set[str] = set()
    for case in CHOICE_CASES:
        out |= set(case.accepts)
    return out


def score(picks: dict[str, str]) -> tuple[int, list[str]]:
    """Score ``{utterance: tool_called}``. Returns (hits, misses described).

    An utterance with no tool call counts as a miss and says so, because
    answering from memory is the failure this corpus exists to catch.
    """
    hits = 0
    misses: list[str] = []
    for case in CHOICE_CASES:
        got = (picks.get(case.utterance) or "").strip()
        if case.hit(got):
            hits += 1
        else:
            misses.append(
                f"{case.utterance!r}: called {got or 'nothing'}, "
                f"wanted one of {', '.join(case.accepts)}"
            )
    return hits, misses
