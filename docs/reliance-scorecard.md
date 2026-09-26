# Reliance scorecard

2026-09-26, after the first pass. Scores are what a person can rely on, not
what a library can do in a test. 10 means they stop opening the other app.

A score moves only when the tool they already hit changed and that change
was watched in the real app. A fixture test checks a function. It is not
a result from the desk. The "Arelis today" slideshow and its pictures
were removed. They were not Arelis running.

| Category | Was | Now | 10 looks like | Still missing for 10 |
|---|---:|---:|---|---|
| Morning plate | 2 | 3 | Opens on its own once mail or the calendar is connected. Time-bound first. No job to configure. | Composer and leave-now line are tested. The window does not show the plate. The schedule skill still says to assemble today by hand. |
| Web | 6 | 6 | First reply is the answer plus one source. A follow-up stays on that page. Logged-in pages open in her browser on that URL. | `StickyDesk` can remember a page. Nothing in the turn calls it. Search can still wander. |
| Mail | 5 | 6 | "Reply to that" drafts and the Allow card is the only ask. People they actually write get surfaced. | Reply now returns `send` and tells her to call `send_email` this turn. It is still two tool calls. `rank_unread` is not wired to the inbox list. |
| Calendar | 6 | 7 | One sentence creates the event, overlap is named, a time pulled out of mail does not get retyped. | Create names a different event on that hour. A time buried in a mail is still retyped by hand. |
| Files | 5 | 5 | The last file stays the file. A created doc opens. | `StickyDesk` resolves "that pdf". The turn does not remember the last path, and a new doc does not open itself. |
| Capture | 4 | 4 | One sentence. A clock means it fires. No clock means it sits on the list. Toast clears it. | `classify_capture` is tested and unused. `remind`, `tasks`, `schedule`, and `goals` are still four doors. A reminder only fires while she is open. |
| Weather | 7 | 7 | Leave-now uses the first event's place, on the morning plate. | `leave_line` is tested and the plate composer will take it. The weather tool and the window do not. |
| Math | 6 | 6 | The number shows up inside the text, the split, or the invoice. | `calculator` is exact. Nothing calls it from inside a draft. |
| Texts | 4 | 4 | "Text Sam I'm leaving" is one draft and one yes. A reply from Sam shows up. Pairing is one test text. | Send and inbound exist. They stay dark until the phone is paired. No handset in this loop. |
| Browser | 4 | 4 | Search opens the page and stops. Logins survive. Pay, book, and delete still pause. | Separate Chrome profile. Live Chrome is not in this test loop. |
| Pictures | 5 | 5 | The image lands in the draft they are already writing. | Comfy generation works. It does not attach itself to a mail or a doc. |
| Look | 5 | 5 | Paste or the screen is enough. The first Allow covers the next look. | Vision and OCR both want a path and a fresh Allow. |

Lanes that landed, each in its own files:

- `arelis/core/reliance/morning.py` is a function. The desk does not show it.
- `arelis/core/reliance/leave_now.py` feeds that plate
- `arelis/core/reliance/conflicts.py` wired into `agenda` create
- `arelis/core/reliance/mail_reply.py` wired into `inbox` reply
- `arelis/core/reliance/last_object.py` tested, not on the turn
- `arelis/core/reliance/capture.py` tested, not on the turn

Next pass, still one lane at a time: mount the plate, call `StickyDesk` from the turn, send `classify_capture` at the remind/task door. Do not put six agents on `orchestrator.py`, `skills.py`, or `policy.py` together.
