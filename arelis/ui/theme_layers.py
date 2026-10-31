"""The room sheet as two layers: structure that never changes, colour that does.

Every room's sheet has the same rules with the same properties; only colour
values differ. Splitting by property family keeps each property in exactly one
layer, so no rule in one layer can override a rule in the other and the
cascade inside each layer is the one the full sheet had.
"""

from __future__ import annotations

import re
from functools import lru_cache

# Properties that carry a room colour, and every property that shares a
# shorthand with one. A border width rides with its colour in `border:`.
COLOUR_FAMILIES = ("background", "border", "color", "selection")

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _is_colour(decl: str) -> bool:
    return decl.split(":", 1)[0].strip().lower().startswith(COLOUR_FAMILIES)


@lru_cache(maxsize=8)
def split_sheet(css: str) -> tuple[str, str]:
    """Return (structural, colour) for one full room sheet."""
    structural: list[str] = []
    colour: list[str] = []
    for match in _RULE.finditer(_COMMENT.sub("", css)):
        selector = " ".join(match.group(1).split())
        decls = [d.strip() for d in match.group(2).split(";") if d.strip()]
        keep = [d for d in decls if not _is_colour(d)]
        paint = [d for d in decls if _is_colour(d)]
        if keep:
            structural.append(f"{selector} {{ {'; '.join(keep)}; }}")
        if paint:
            colour.append(f"{selector} {{ {'; '.join(paint)}; }}")
    return "\n".join(structural), "\n".join(colour)
