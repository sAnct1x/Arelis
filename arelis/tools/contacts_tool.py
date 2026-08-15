"""Read and edit data/contacts.yaml through the confirm gate.

list/get are free. add/update/remove need approval. Incomplete adds fail with a
clear ask-the-user message so the model gathers the number in chat first — same
flow as setting the book up by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arelis.contacts import (
    CONTACTS_PATH,
    add_contact,
    format_contact,
    load_contacts,
    remove_contact,
    resolve_contact,
    update_contact,
)
from arelis.tools.base import ToolResult

WRITE_ACTIONS = frozenset({"add", "update", "remove"})


class ContactsTool:
    name = "contacts"
    description = (
        "List, look up, add, update, or remove people in data/contacts.yaml "
        "(used by send_sms). When the user wants to add someone, ask in chat "
        "for anything still missing — at least a short id and a phone number — "
        "plus name and other nicknames if they have them. Do not invent a "
        "number. Writes are confirmed by the user before they are saved."
    )
    # list/get are free; needs_confirm special-cases write actions.
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get", "add", "update", "remove"],
                "description": (
                    "list all contacts, get one, add a new one, update an "
                    "existing one, or remove one"
                ),
            },
            "id": {
                "type": "string",
                "description": (
                    "Primary key for action=add (short, like 'dave' or 'coach'). "
                    "Also accepted as who for update/remove/get."
                ),
            },
            "who": {
                "type": "string",
                "description": (
                    "Any nickname for get/update/remove (wife, brother, mom…)."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "Display name for add/update. Also accepted as who "
                    "for get (alias or name)."
                ),
            },
            "phone": {
                "type": "string",
                "description": "Phone number. Required for add.",
            },
            "aliases": {
                "type": "string",
                "description": (
                    "Extra nicknames, comma-separated "
                    "(e.g. 'robin, robin hale'). Merged on update unless "
                    "replace_aliases is true."
                ),
            },
            "email": {
                "type": "string",
                "description": "Optional email address for this person",
            },
            "replace_aliases": {
                "type": "boolean",
                "description": (
                    "For update: if true, replace the alias list instead of "
                    "merging. Default false."
                ),
            },
        },
        "required": ["action"],
    }

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONTACTS_PATH

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "list":
            return self._list()
        if action == "get":
            return self._get(
                str(
                    kwargs.get("who")
                    or kwargs.get("id")
                    or kwargs.get("name")
                    or ""
                )
            )
        if action == "add":
            return self._add(kwargs)
        if action == "update":
            return self._update(kwargs)
        if action == "remove":
            return self._remove(str(kwargs.get("who") or kwargs.get("id") or ""))
        return ToolResult(
            ok=False,
            output="Unknown action. Use list, get, add, update, or remove.",
        )

    def _list(self) -> ToolResult:
        book = load_contacts(self.path)
        if not book:
            return ToolResult(
                ok=True,
                output=(
                    "No contacts yet. Add one with action=add after asking the "
                    "user for an id and a phone number."
                ),
                data={"contacts": []},
            )
        lines = [format_contact(c) for c in book.values()]
        lines.append("")
        lines.append(f"{len(book)} contact(s) in {self.path.name}.")
        return ToolResult(
            ok=True,
            output="\n\n".join(lines),
            data={
                "contacts": [
                    {
                        "id": c.alias,
                        "name": c.display_name,
                        "phone": c.phone,
                        "aliases": list(c.aliases),
                    }
                    for c in book.values()
                ]
            },
        )

    def _get(self, who: str) -> ToolResult:
        who = who.strip()
        if not who:
            return ToolResult(ok=False, output="Pass who= (or id=) to look someone up.")
        contact = resolve_contact(who, load_contacts(self.path))
        if contact is None:
            return ToolResult(ok=False, output=f"No contact matches {who!r}.")
        return ToolResult(
            ok=True,
            output=format_contact(contact),
            data={
                "id": contact.alias,
                "name": contact.display_name,
                "phone": contact.phone,
                "aliases": list(contact.aliases),
                "email": contact.email,
            },
        )

    def _add(self, kwargs: dict[str, Any]) -> ToolResult:
        key = str(kwargs.get("id") or kwargs.get("who") or "").strip()
        result = add_contact(
            key=key,
            name=str(kwargs.get("name") or ""),
            phone=str(kwargs.get("phone") or ""),
            aliases=kwargs.get("aliases"),
            email=str(kwargs.get("email") or ""),
            path=self.path,
        )
        if isinstance(result, str):
            return ToolResult(ok=False, output=result)
        return ToolResult(
            ok=True,
            output=f"Added contact:\n{format_contact(result)}",
            data={"id": result.alias, "name": result.display_name},
        )

    def _update(self, kwargs: dict[str, Any]) -> ToolResult:
        who = str(kwargs.get("who") or kwargs.get("id") or "").strip()
        if not who:
            return ToolResult(ok=False, output="Pass who= (or id=) to update someone.")
        result = update_contact(
            who=who,
            name=str(kwargs.get("name") or ""),
            phone=str(kwargs.get("phone") or ""),
            aliases=kwargs.get("aliases"),
            email=str(kwargs.get("email") or ""),
            replace_aliases=bool(kwargs.get("replace_aliases")),
            path=self.path,
        )
        if isinstance(result, str):
            return ToolResult(ok=False, output=result)
        return ToolResult(
            ok=True,
            output=f"Updated contact:\n{format_contact(result)}",
            data={"id": result.alias, "name": result.display_name},
        )

    def _remove(self, who: str) -> ToolResult:
        who = who.strip()
        if not who:
            return ToolResult(ok=False, output="Pass who= (or id=) to remove someone.")
        result = remove_contact(who, path=self.path)
        if isinstance(result, str):
            return ToolResult(ok=False, output=result)
        return ToolResult(
            ok=True,
            output=f"Removed {result.display_name} ({result.alias}).",
            data={"id": result.alias},
        )
