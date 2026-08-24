"""Named multi-turn soak scripts (offline + live)."""

from __future__ import annotations

from arelis.eval.conversation import ConversationTurn, tool_call


def production_bounce_turns() -> list[ConversationTurn]:
    """SMS → agenda → SMS → weather → delete → create → image → vision → email → inject."""
    return [
        ConversationTurn(
            id="sms_love",
            user="Send a text to my wife saying that I love her",
            expect_tools=("send_sms",),
            require_args=("to", "body"),
            expect_args={"to": "wife", "body": "love"},
            forbid_claim_if_no_tool=("sent", "i texted", "message went"),
            notes="Happy-path SMS with locked contact + body.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "send_sms",
                                {"to": "wife", "body": "I love her"},
                            )
                        ],
                    )
                ],
                [("token", "Sent your wife: I love her.")],
            ],
        ),
        ConversationTurn(
            id="sms_text_message_not_to_message",
            user=(
                "in a text message to my wife and just tell her "
                "good nights, sweet dreams"
            ),
            expect_tools=("send_sms",),
            require_args=("to", "body"),
            expect_args={"to": "wife", "body": "sweet dreams"},
            forbid_claim_if_no_tool=("sent", "i texted", "message went"),
            notes="STT 'text message to my wife' must not parse to=message.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "send_sms",
                                {
                                    "to": "message",
                                    "body": "good nights, sweet dreams",
                                },
                            )
                        ],
                    )
                ],
                [("token", "Sent your wife: good nights, sweet dreams.")],
            ],
        ),
        ConversationTurn(
            id="agenda_create_anniversary",
            user=(
                "Create a calendar event on August 13th at 7am. "
                "It is my anniversary"
            ),
            expect_tools=("agenda",),
            require_args=("action", "summary", "start"),
            expect_args={"action": "create", "summary": "Anniversary"},
            forbid_claim_if_no_tool=("created", "i added", "on your calendar"),
            notes="Month-name create with year lock.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "agenda",
                                {
                                    "action": "create",
                                    "provider": "google",
                                    "summary": "Anniversary",
                                    "start": "2026-08-13T07:00:00-04:00",
                                },
                            )
                        ],
                    )
                ],
                [
                    (
                        "token",
                        "Created your anniversary event for August 13th at 7am.",
                    )
                ],
            ],
        ),
        ConversationTurn(
            id="sms_miss_you",
            user=(
                "Send her another text and tell her that our anniversary is in "
                "two days and I will miss her"
            ),
            expect_tools=("send_sms",),
            require_args=("to", "body"),
            expect_args={"to": "wife", "body": "miss"},
            notes="Second SMS — must not invent Hello-from-Arelis junk.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "send_sms",
                                {
                                    "to": "wife",
                                    "body": (
                                        "Our anniversary is in two days and "
                                        "I will miss her"
                                    ),
                                },
                            )
                        ],
                    )
                ],
                [("token", "Sent the anniversary note to your wife.")],
            ],
        ),
        ConversationTurn(
            id="weather_outside",
            user="What is the weather like outside here in Springfield, Illinois?",
            expect_tools=("weather",),
            notes="Weather tool only — no AccuWeather scrape.",
            script=[
                [("tool_calls", [tool_call("weather", {"days": 3})])],
                [
                    (
                        "token",
                        "It is about 68.7°F and overcast in Springfield, Illinois.",
                    )
                ],
            ],
        ),
        ConversationTurn(
            id="agenda_delete",
            user="Delete that anniversary calendar event you just created",
            expect_tools=("agenda",),
            require_args=("action",),
            expect_args={"action": "delete"},
            notes="Delete uses the stub event id from the prior create.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "agenda",
                                {
                                    "action": "delete",
                                    "provider": "google",
                                    "event_id": "{{EVENT_ID}}",
                                },
                            )
                        ],
                    )
                ],
                [("token", "Deleted the anniversary event.")],
            ],
        ),
        ConversationTurn(
            id="agenda_create_reminder",
            user=(
                "Create a calendar event for tomorrow at 4pm to remind me "
                "to text my wife that I love her"
            ),
            expect_tools=("agenda",),
            require_args=("action", "summary"),
            expect_args={"action": "create"},
            notes="Create after delete — must not thrash contacts/web_search.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "agenda",
                                {
                                    "action": "create",
                                    "provider": "google",
                                    "summary": "Reminder: text wife",
                                    "start": "2026-08-12T16:00:00-04:00",
                                    "description": "text my wife that I love her",
                                },
                            )
                        ],
                    )
                ],
                [("token", "Created a 4pm reminder to text your wife.")],
            ],
        ),
        ConversationTurn(
            id="image_generate",
            user="Generate a photo of a quiet Illinois farmhouse at dusk",
            expect_tools=("image",),
            notes="Comfy stub writes a real PNG under outputs/images/soak/.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "image",
                                {"prompt": "quiet Illinois farmhouse at dusk"},
                            )
                        ],
                    )
                ],
                [("token", "Generated the farmhouse image and saved it.")],
            ],
        ),
        ConversationTurn(
            id="vision_describe",
            user="Describe the photo you just generated",
            expect_tools=("vision",),
            require_args=("path",),
            notes="Vision on the generated path ({{IMAGE_PATH}}).",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "vision",
                                {"path": "{{IMAGE_PATH}}"},
                            )
                        ],
                    )
                ],
                [
                    (
                        "token",
                        "It looks like a simple demo diagram with three labeled boxes.",
                    )
                ],
            ],
        ),
        ConversationTurn(
            id="email_with_attach",
            user=(
                "Email that image to you@example.com with subject "
                "Farmhouse photo"
            ),
            expect_tools=("send_email",),
            require_args=("to", "subject"),
            expect_args={
                "to": "you@example.com",
                "subject": "Farmhouse",
            },
            notes="Compose email with attach=generated path — no contact search.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "send_email",
                                {
                                    "to": "you@example.com",
                                    "subject": "Farmhouse photo",
                                    "body": "Here is the farmhouse image.",
                                    "attach": "{{IMAGE_PATH}}",
                                },
                            )
                        ],
                    )
                ],
                [
                    (
                        "token",
                        "Emailed the farmhouse photo to you@example.com.",
                    )
                ],
            ],
        ),
        ConversationTurn(
            id="sms_inject_after_search",
            user="Text my wife saying dinner is at 7",
            expect_tools=("send_sms",),
            require_args=("to", "body"),
            expect_args={"to": "wife", "body": "dinner"},
            notes="First web_search redirect injects send_sms from draft.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "web_search",
                                {"query": "Robin Hale phone number"},
                            )
                        ],
                    )
                ],
                [
                    (
                        "tool_calls",
                        [
                            tool_call(
                                "web_search",
                                {"query": "Robin Hale contact information"},
                            )
                        ],
                    )
                ],
                [("token", "Sent your wife: dinner is at 7.")],
            ],
        ),
        ConversationTurn(
            id="fanout_weather_inbox",
            user="What's the weather today, and anything new in my inbox?",
            expect_tools=("weather", "inbox"),
            notes="Same-round independent reads — fan-out, not serial.",
            script=[
                [
                    (
                        "tool_calls",
                        [
                            tool_call("weather", {"days": 3}),
                            tool_call("inbox", {"action": "list"}),
                        ],
                    )
                ],
                [
                    (
                        "token",
                        "Overcast in Springfield, Illinois. Inbox list came "
                        "back from the stub.",
                    )
                ],
            ],
        ),
    ]


def _shot(
    turn_id: str,
    user: str,
    tool: str,
    args: dict | None = None,
    token: str = "Done.",
) -> ConversationTurn:
    """One scripted tool call then a short final answer."""
    return ConversationTurn(
        id=turn_id,
        user=user,
        expect_tools=(tool,),
        script=[
            [("tool_calls", [tool_call(tool, args or {})])],
            [("token", token)],
        ],
    )


def limb_catalog_turns() -> list[ConversationTurn]:
    """One AgentLoop bounce per registered tool (stubs, auto-Allow)."""
    return [
        _shot("calc", "What is 17*19?", "calculator", {"expression": "17*19"}),
        _shot(
            "python",
            "How far does a ball go if I throw it from 5 m at 5 m/s at 45 degrees?",
            "python",
            {
                "code": (
                    "g=9.81; h=5; v=5; th=radians(45); "
                    "vx=v*cos(th); vy=v*sin(th); "
                    "a=0.5*g; disc=vy*vy+2*g*h; t=(vy+sqrt(disc))/g; "
                    "vx*t"
                )
            },
        ),
        _shot(
            "ws_write",
            "Create hello.py with a function that returns 1",
            "workspace",
            {
                "action": "write",
                "path": "hello.py",
                "content": "def n():\n    return 1\n",
            },
        ),
        _shot(
            "ws_read",
            "Read hello.py",
            "workspace",
            {"action": "read", "path": "hello.py"},
        ),
        _shot(
            "ws_list",
            "List files in the project",
            "workspace",
            {"action": "list", "path": "."},
        ),
        _shot(
            "analyze",
            "Summarize sales.csv",
            "analyze",
            {"path": "sales.csv", "action": "summary"},
        ),
        _shot("git", "What's the git status?", "git_info", {"action": "status"}),
        _shot(
            "doc",
            "What does the PDF say?",
            "doc_extract",
            {"path": "note.pdf"},
        ),
        _shot("recall", "What did I say about the deadline?", "recall", {"query": "deadline"}),
        _shot(
            "memory",
            "Remember that the e2e token is catalog",
            "memory",
            {"action": "remember", "fact": "the e2e token is catalog"},
        ),
        _shot(
            "tasks",
            "Add a task: pack cables",
            "tasks",
            {"action": "add", "title": "pack cables"},
        ),
        _shot(
            "goals",
            "Add a goal: ship the catalog",
            "goals",
            {"action": "add", "title": "ship the catalog"},
        ),
        _shot(
            "attention",
            "What needs my attention?",
            "tasks",
            {"action": "list"},
        ),
        _shot(
            "contacts",
            "Look up my wife in contacts",
            "contacts",
            {"action": "get", "who": "wife"},
        ),
        _shot("location", "Where am I?", "user_location", {}),
        _shot("weather", "What's the weather?", "weather", {"days": 3}),
        _shot("inbound", "Did anyone text me?", "inbound_sms", {}),
        _shot("inbox", "Check my inbox", "inbox", {"action": "list"}),
        _shot(
            "sms",
            "Text Brian: catalog soak",
            "send_sms",
            {"to": "Brian", "body": "catalog soak"},
        ),
        _shot(
            "email",
            "Email me a catalog note",
            "send_email",
            {
                "to": "you@example.com",
                "subject": "catalog",
                "body": "soak",
            },
        ),
        _shot("agenda", "What's on my calendar today?", "agenda", {"action": "today"}),
        _shot("schedule", "List scheduled jobs", "schedule", {"action": "list"}),
        _shot("clipboard", "What's on my clipboard?", "clipboard", {}),
        _shot("ocr", "OCR this screenshot", "ocr", {"action": "text", "path": "shot.png"}),
        _shot("camera", "Take a camera snapshot", "camera", {"action": "snapshot"}),
        _shot("image", "Generate a blue circle", "image", {"prompt": "blue circle"}),
        _shot("vision", "Describe this image", "vision", {"path": "outputs/images/demo.png"}),
        _shot("browser", "Pull up YouTube", "browser", {"action": "open", "url": "youtube"}),
        _shot(
            "search",
            "Search the web for local-first agents",
            "web_search",
            {"query": "local-first agents"},
        ),
        _shot("fetch", "Fetch example.com", "web_fetch", {"url": "https://example.com"}),
        _shot("scrape", "Scrape example.com", "scrape", {"url": "https://example.com"}),
        _shot(
            "research",
            "Write a research report on example.com",
            "research_report",
            {"query": "What is example.com used for?"},
        ),
    ]
