"""Plain explanation of hands and desk voice. She says this; she does not invent it."""

from __future__ import annotations

import re

# Whole sentence. "open history" and "how is the weather" must not land here.
_GUIDE = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey\s+)? (?:arelis\s*[,:]?\s*)?
    (?:please\s+)?
    (?:can\s+you\s+|could\s+you\s+)?
    (?:
        how\s+(?:do|does|can)\s+
        (?:i\s+|you\s+|we\s+)?
        (?:use\s+|control\s+(?:you\s+)?(?:with\s+)?)?
        (?:my\s+|the\s+|this\s+)?
        (?:
            hands? | gestures? | pinch(?:es|ing)? |
            voice(?:\s+control|\s+commands?)? |
            filament(?:\s+desk)? | desk
        )
        (?:\s+work)?
        |
        (?:explain|tell\s+me(?:\s+about)?|walk\s+me\s+through|show\s+me)
        (?:\s+how)?\s+
        (?:the\s+|my\s+|this\s+)?
        (?:
            hands? | gestures? | pinch(?:es|ing)? |
            voice(?:\s+control|\s+commands?)? |
            filament(?:\s+desk)? | desk(?:\s+controls?)?
        )
        (?:\s+works?)?
        |
        what\s+can\s+i\s+say
        |
        how\s+do\s+i\s+control\s+(?:you|arelis)
        |
        how\s+do\s+i\s+(?:drag|move|grab)\s+
        (?:a\s+|the\s+)?(?:windows?|tiles?)
    )
    \s*[.?!]?\s*$
    """
)

DESK_GUIDE = """\
Hands

A pinch is thumb and index together. That is the only gesture.

Hold the pinch still, then open your fingers. That is a click, on the spot where they closed.

Pinch a gold word or a bead and that tile opens.

Pinch a button or a row and it clicks. Pinch that same row again and it
opens, the way a double-click does.

Move while the pinch is still closed and you are grabbing. Grab empty
glass, the edge, or the title and the window follows. A list, a button,
or a text field stays a click, so a row does not turn into a drag.

Two pinches on one tile resize it. Spread your hands and it grows.
Bring them together and it shrinks. Opening both without spreading
does not click. One pinch still moves it.

Let go of a window quickly and it flicks across the screens.

An open hand over a list scrolls it when the hand actually moves.
A hand sitting still does not. Hand up, the list goes up.

Reality uses the same pinch. That is the shapes area: the balls, the
squares, the rest of them. Move, and the shape follows. Turn your
wrist and it turns. Reach toward the camera or pull back and it comes
closer or goes farther. Two pinches resize it, the same way two pinches
resize a tile. One pinch that does not move does not grab.

On the solar view, a moving pinch looks around. A still pinch does not.

The mouse still works. On a disc it is the same pinch.

Turn hands on from the chip in the title bar. Rest, minimize, or leave
filament and the camera turns off. Hands run in this dev checkout.
The installed app does not track them.

Voice

These happen right away. I do not sit and think about them.

Open or close a tile by name. History, thinking, files, days, camera,
notify, contacts, chat, reality.

"Open history." "Close files." "Open days."

"Span 1", "span 2", "span 3", or "two screens."

"Close this" closes the tile you are in, or the last one you opened or grabbed.

"Open rooms" opens the rooms menu. "Open the notes room" still switches rooms.

Stop, pause, go, yes, and no already land without starting a chat turn.

What still takes a normal sentence

Mail, the browser, calendar events, settings, and quitting. Ask for those the usual way.

A form, a right-click menu, and dragging a tile's edge to resize it are still the mouse.

Ask "how do hands work" anytime and I will say this again.
"""


def match_desk_guide(text: str) -> bool:
    """True when they asked how hands or desk voice works."""
    return _GUIDE.match(text or "") is not None


def desk_guide_text() -> str:
    return DESK_GUIDE.strip()
