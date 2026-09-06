"""Twenty live glass prompts — real SMS, mail, calendar, files, math, research.

Image generate/edit and Reality/Earth are out of this board (other sittings).
Side-effect turns embed TOKEN so Gmail and Calendar can be searched.
SMS is out of this board — phone grant is a later sitting.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from arelis.eval.conversation import ConversationTurn

BOARD_ID = "BRD-0000"
KEEP_MARK = "stay"
SCRATCH_MARK = "toss"

# Per-turn ceilings. Research and the report disposer run long on 9B.
TIMEOUT_S: dict[str, float] = {
    "T16_research": 420,
    "T17_deep_research": 720,
    "T20_tasks": 360,
}

FORBIDDEN_TOOLS = frozenset(
    {"image", "image_edit", "earth", "solar", "camera", "vision", "send_sms"}
)


def _tomorrow_iso(hour: int, minute: int) -> str:
    day = datetime.now().date() + timedelta(days=1)
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:00"


def live_board_turns(*, token: str = BOARD_ID) -> list[ConversationTurn]:
    """Twenty user prompts, easy → hard, covering the attended surface."""
    keep = f"Arelis {KEEP_MARK} {token}"
    scratch = f"Arelis {SCRATCH_MARK} {token}"
    note_path = f"outputs/live_board/{token.lower()}-log.md"
    keep_start = _tomorrow_iso(15, 0)
    keep_end = _tomorrow_iso(15, 30)
    toss_start = _tomorrow_iso(15, 45)
    toss_end = _tomorrow_iso(16, 0)
    return [
        ConversationTurn(
            id="T01_math_easy",
            user="What is 12.5% of 640?",
            expect_tools=("calculator",),
            expect_answer_contains=("80",),
            notes="Easy arithmetic — calculator, not a recited guess.",
        ),
        ConversationTurn(
            id="T02_units",
            user="Convert 90 degrees Fahrenheit to Celsius.",
            expect_tools=("units", "calculator"),
            expect_tools_any=True,
            expect_answer_contains=("32.2",),
            notes="Unit conversion must call units.",
        ),
        ConversationTurn(
            id="T03_math_compound",
            user="What is 19 times 47? Show the product.",
            expect_tools=("calculator", "python"),
            expect_tools_any=True,
            expect_answer_contains=("893",),
            notes="Medium multiply — tool, not a recited guess.",
        ),
        ConversationTurn(
            id="T04_cas_integral",
            user="Differentiate x^3 * log(x) with respect to x.",
            expect_tools=("cas",),
            expect_answer_contains=("log",),
            notes="Symbolic derivative — cas, not a recited formula.",
        ),
        ConversationTurn(
            id="T05_math_hard",
            user=(
                "Using python, print the 12th Fibonacci number. "
                "Use F1=1, F2=1, so F12 is the value I want."
            ),
            expect_tools=("python", "cas"),
            expect_tools_any=True,
            expect_answer_contains=("144",),
            notes="Hard-enough scripted number — F12 = 144.",
        ),
        ConversationTurn(
            id="T06_csv_write",
            user=(
                f"Write a CSV file at outputs/live_board/{token.lower()}-rows.csv "
                f"with header item,note and one data row: check,{token}."
            ),
            expect_tools=("workspace", "document"),
            expect_tools_any=True,
            forbid_claim_if_no_tool=("wrote", "saved the file"),
            notes="CSV artifact — SMS is out of this board.",
        ),
        ConversationTurn(
            id="T07_sqrt",
            user=(
                "Using python, print the square root of 2 to at least 8 decimal places."
            ),
            expect_tools=("python", "calculator"),
            expect_tools_any=True,
            expect_answer_contains=("1.41421356",),
            notes="Numeric root — tool, not a recited guess.",
        ),
        ConversationTurn(
            id="T08_email_me",
            user=(
                f"Email me with subject Arelis board {token} and body: "
                "Board mail check. If this is in Gmail, send works."
            ),
            expect_tools=("send_email",),
            require_args=("subject", "body"),
            expect_args={"subject": token},
            forbid_claim_if_no_tool=("sent the email", "i emailed"),
            notes="Real mail to the owner inbox. Search Gmail for the token.",
        ),
        ConversationTurn(
            id="T09_cal_keep",
            user=(
                f"Create a calendar event titled {keep}. "
                f"Use agenda action=create with start={keep_start} and "
                f"end={keep_end} (tomorrow 3:00–3:30 PM). Leave it on the calendar."
            ),
            expect_tools=("agenda",),
            require_args=("action",),
            expect_args={"action": "create", "summary": KEEP_MARK},
            forbid_claim_if_no_tool=("created", "i added", "on your calendar"),
            notes="Keep this event — it should land on the phone calendar.",
        ),
        ConversationTurn(
            id="T10_cal_scratch",
            user=(
                f"Create a second calendar event titled {scratch}. "
                f"Use agenda action=create with start={toss_start} and "
                f"end={toss_end} (tomorrow 3:45–4:00 PM)."
            ),
            expect_tools=("agenda",),
            require_args=("action",),
            expect_args={"action": "create", "summary": SCRATCH_MARK},
            forbid_claim_if_no_tool=("created", "i added", "on your calendar"),
            notes="Scratch event created only so the next turn can delete it.",
        ),
        ConversationTurn(
            id="T11_cal_delete",
            user=(
                f"Delete only the calendar event titled {scratch}. "
                f"Do not delete {keep}."
            ),
            expect_tools=("agenda",),
            require_args=("action",),
            expect_args={"action": "delete"},
            forbid_claim_if_no_tool=("deleted", "i removed", "it's gone"),
            notes="Destructive delete of the scratch event only.",
        ),
        ConversationTurn(
            id="T12_file_write",
            user=(
                f"Write a short markdown file at {note_path} that says this "
                f"file was created by the Arelis live board ({token})."
            ),
            expect_tools=("workspace", "document"),
            expect_tools_any=True,
            forbid_claim_if_no_tool=("wrote", "saved the file"),
            notes="File creation via workspace write or document.",
        ),
        ConversationTurn(
            id="T13_doc_create",
            user=(
                f"Create a markdown document titled Board log {token} "
                "with a one-paragraph body saying the live board wrote this document."
            ),
            expect_tools=("document",),
            expect_args={"format": "md"},
            forbid_claim_if_no_tool=("wrote", "saved", "created"),
            notes="Document tool markdown artifact.",
        ),
        ConversationTurn(
            id="T14_doc_convert",
            user=(
                "Convert that markdown document you just created to a PDF. "
                "Use the document tool with format pdf and from_path set to "
                "the file you just wrote."
            ),
            expect_tools=("document",),
            expect_args={"format": "pdf"},
            forbid_claim_if_no_tool=("converted", "pdf", "wrote"),
            notes="Format conversion: markdown → PDF.",
        ),
        ConversationTurn(
            id="T15_weather",
            user="What's the forecast for tomorrow?",
            expect_tools=("weather",),
            notes="Weather tool, not an AccuWeather scrape.",
        ),
        ConversationTurn(
            id="T16_research",
            user=(
                "What is the current status of ESA's JUICE mission at Jupiter? "
                "Cite the sources you used."
            ),
            expect_tools=("web_search", "scrape", "research_report"),
            expect_tools_any=True,
            forbid_claim_if_no_tool=("according to", "esa said"),
            notes="Live research: search + scrape (or the report disposer).",
        ),
        ConversationTurn(
            id="T17_deep_research",
            user=(
                "Write a sourced research report on solid-state battery "
                "production scale-up in 2025 and 2026."
            ),
            expect_tools=("research_report",),
            require_args=("query",),
            forbid_claim_if_no_tool=("according to", "sources show"),
            notes="Deep research disposer — artifact under outputs/research/.",
        ),
        ConversationTurn(
            id="T18_agenda_today",
            user="What's on my calendar this weekend?",
            expect_tools=("agenda",),
            notes="Read path — no invented meetings.",
        ),
        ConversationTurn(
            id="T19_inbox",
            user="Do I have any unread email? List only the subjects.",
            expect_tools=("inbox",),
            forbid_claim_if_no_tool=("you have an email", "unread from"),
            notes="Inbox warrant before claiming mail.",
        ),
        ConversationTurn(
            id="T20_tasks",
            user=f"Add a task: file the {token} board notes.",
            expect_tools=("tasks",),
            expect_args={"action": "add"},
            forbid_claim_if_no_tool=("added", "i'll track"),
            notes="Checkable task, not a memory fact.",
        ),
    ]


LIVE_BOARD = live_board_turns()
