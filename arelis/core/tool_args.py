"""Reject a tool call whose arguments belong to a different tool.

Small local models carry arguments across turns. After a cancelled SMS turn the
7B answered "what is 17 times 19?" with ``calculator(to="wife", body="I love
you.")``, and because tools accept ``**kwargs`` and read only the keys they
declare, that landed as a bland "Missing expression." — a silent miss the model
retried instead of a correction it could act on.

The judgement is schema-driven on purpose. An earlier keyword-only version
flagged any call carrying a recipient and a body, which would also have hit
``browser``, whose own schema declares both ``text`` and ``phone``. Only
arguments the tool never declared can be evidence that another tool was meant.

Nothing here is about safety; ``needs_confirm`` and Allow still own that. This
is about telling the model it grabbed the wrong tool while there is still a
round left to fix it.
"""

from __future__ import annotations

from typing import Any

# The send_sms / send_email shape. A recipient alone is too weak to judge on, so
# a recipient plus a message body is what marks an undeclared argument set as an
# outbound send wearing another tool's name.
_RECIPIENT_KEYS = frozenset({"to", "recipient", "phone", "number"})
_BODY_KEYS = frozenset({"body", "message", "sms", "text"})


def schema_keys(schema: Any) -> set[str]:
    """Declared parameter names for a tool, lowercased."""
    if not isinstance(schema, dict):
        return set()
    props = schema.get("properties")
    if not isinstance(props, dict):
        return set()
    return {str(k).strip().lower() for k in props}


def cross_tool_arg_error(
    name: str,
    args: dict[str, Any] | None,
    *,
    declared: set[str] | None = None,
    strict: bool = False,
) -> str | None:
    """Explain why this call is the wrong tool, or None when it is fine.

    ``declared`` is the tool's own parameter names. Without it nothing is
    rejected: guessing which keys a tool owns is how false positives start.
    An empty set counts as "without it". A schema that declares no properties
    is an open schema, not a tool that accepts nothing, and reading it the
    strict way rejected every argument of every such tool.

    ``strict`` also corrects the partial case: valid arguments carrying one the
    tool never declared. Tools take ``**kwargs``, so that argument is dropped in
    silence, and the reply is then built on a belief the tool never honoured —
    ``weather(days=2, latitude=39.7)`` answers for the profile location and says
    nothing about having ignored the coordinate. Being told beats being obeyed
    halfway.
    """
    tool = (name or "").strip()
    if not tool or not args or not declared:
        return None
    keys = {str(k).strip().lower() for k in args.keys()}
    if not keys:
        return None
    stray = keys - declared
    if not stray:
        return None

    if (stray & _RECIPIENT_KEYS) and (stray & _BODY_KEYS):
        return (
            f"Rejected: `{tool}` does not take {_shape(stray)} and does not "
            "send messages. That is a send_sms call. Call send_sms to text "
            f"someone, or call `{tool}` with its own arguments"
            f"{_own(declared)}."
        )
    if stray == keys:
        # Every argument is foreign: the model kept the last call's arguments
        # and only changed the tool name.
        return (
            f"Rejected: `{tool}` takes none of {', '.join(sorted(stray))}. "
            f"Call it with its own arguments{_own(declared)}, or call the tool "
            "those arguments belong to."
        )
    if strict:
        kept = sorted(keys & declared)
        return (
            f"Rejected: `{tool}` does not take {', '.join(sorted(stray))}. "
            f"It would be ignored rather than applied, so the answer would look "
            f"like it was honoured. Call `{tool}` again with only"
            f"{_own(declared)}"
            + (f" — {', '.join(kept)} was fine — " if kept else " ")
            + "or use the tool that does take it."
        )
    return None


def _shape(keys: set[str]) -> str:
    ordered = [k for k in ("to", "recipient", "phone", "number") if k in keys][:1]
    ordered += [k for k in ("body", "message", "sms", "text") if k in keys][:1]
    return "/".join(ordered) or "those arguments"


def _own(declared: set[str]) -> str:
    if not declared:
        return ""
    return " (" + ", ".join(sorted(declared)) + ")"


__all__ = ["cross_tool_arg_error", "schema_keys"]
