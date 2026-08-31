"""Short, byte-stable prompt pieces. Essays stay in skill cards for humans.

Ollama sees this module, not the card bodies. The tool JSON array still
lists every tool every turn (prefix cache). Descriptions and param
essays do not.
"""

from __future__ import annotations

from typing import Any

# One line per tool. Names + enums in the schema do the rest.
_SHORT_DESC: dict[str, str] = {
    "agenda": "local calendar. action=today|tomorrow|list|create|update|delete|close",
    "analyze": "CSV / table stats. path required",
    "browser": "her Chrome. no passwords/OTP. stop captcha|Pay. click text|ref|nth",
    "calculator": "arithmetic. expression required",
    "camera": "webcam snapshot. inspect only",
    "cas": "symbolic math. action=simplify|solve|diff|integrate|…",
    "catalog": "pinned live feeds. action=list|get",
    "clipboard": "read / write OS clipboard",
    "contacts": "local address book. action=list|get|add|update|remove",
    "diagnostics": "local pytest / doctor. not a web search",
    "doc_extract": "text from pdf/docx/xlsx on disk",
    "document": "write md/pdf/csv under outputs",
    "earth": "Reality look / bands. not a web search",
    "git_info": "git status / log / diff in the workspace",
    "goals": "long-lived goals. action=list|add|done|drop",
    "image": "generate an image. confirm first",
    "image_edit": "edit a local image. confirm first",
    "inbound_sms": "recent inbound texts. do not invent replies",
    "inbox": "Gmail list/search/trash/archive. never claim delete without a tool",
    "memory": "remember / forget durable facts. memory tool",
    "ocr": "read text in an image",
    "plot": "write a chart file under outputs",
    "python": "run a short Python snippet",
    "recall": "search memory before claiming you do not know",
    "research_report": "multi-source writeup under outputs/research",
    "rooms": "list / go to a room. Reality is physics",
    "schedule": "local jobs. action=list|create|run|delete",
    "scrape": "readable page text. Prefer scrape for news/docs",
    "send_email": "send mail. confirm card. never invent sent",
    "send_sms": "text via the user's phone. confirm card",
    "solar": "Reality sim. flag / time / load. not a web search",
    "tasks": "short list. action=list|add|done|drop",
    "tile": "View menu. action=open|close name=thinking|history|chat|…",
    "units": "unit convert",
    "user_location": "user's saved place. not a web guess",
    "vision": "describe a local image",
    "watch": "house doors snapshot. not antivirus",
    "weather": "forecast. call the weather tool. place=name, not coords",
    "web_fetch": "http(s) APIs / JSON. not pages",
    "web_search": "search first. never guess a url",
    "workspace": "read/write/list sandbox files. writes confirm",
}


# Shipped every turn. Telegraph. Keywords tests lock are intentional.
COMPACT_TOOL_POLICY = """
tools: call; don't invent results. Never ask "Would you like me to proceed / fetch / scrape / search / check?" when the ask is clear. Multi-part: keep calling until done. Fallback: {"tool":"<name>","args":{}} or {"final":"<answer>"}.
confirm: writes/sends = card, not a chat ask. Never claim a side effect unless a tool this turn succeeded. Confirmation without a tool is a lie.
browser: her Chrome; no password/OTP; stop captcha|Pay; click text|ref|nth. no goto_sign_in.
web: web_search first; never guess a url; never answer from a snippet alone; never pass the title as url (copy the URL: value); Prefer scrape for pages; web_fetch for apis.
weather: call the weather tool; not search; not scrape; place=name; two cities = two calls.
location: user_location; do not web-guess.
sms: call send_sms immediately when to+body are known; do not re-ask for the body; inbound_sms for "did they text"; contacts for the book.
email: inbox list/search/trash/archive; send_email to send; never claim you deleted mail.
workspace: workspace read/write/list; inspect source with workspace; writes confirm.
attach: image→vision|ocr; pdf→doc_extract; csv→analyze; text→workspace. never invent file contents.
memory: recall before claiming you do not know; remember/forget via the memory tool.
goals: goals. tasks: tasks. analyze: analyze. doc_extract: doc_extract. document: document. calculator: calculator. diagnostics: diagnostics. cas: cas. clipboard: clipboard. ocr: ocr.
agenda: agenda (events). tile: tile (thinking|workspace|history|chat|…; filament chat = name=chat). rooms: rooms. schedule: schedule.
image: image. image_edit: image_edit. vision: vision. research_report: research_report.
solar: solar. earth: earth. catalog: catalog. plot: plot. units: units. python: python. watch: watch. git_info: git_info. camera: camera.
""".strip()


def compact_tool_policy() -> str:
    """The policy Ollama sees. Skill cards stay in skills.py for hints."""
    return COMPACT_TOOL_POLICY


def skinny_description(name: str, fallback: str = "") -> str:
    short = _SHORT_DESC.get((name or "").strip())
    if short:
        return short
    raw = (fallback or "").strip().replace("\n", " ")
    if not raw:
        return (name or "tool").strip() or "tool"
    cut = raw.split(". ", 1)[0].strip()
    if len(cut) > 140:
        cut = cut[:137].rstrip() + "…"
    return cut


def skinny_parameters(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Keep types, enums, required, property names. Drop description essays."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    return _strip_descriptions(schema)


def skinny_ollama_tool(
    name: str,
    description: str,
    parameters_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": skinny_description(name, description),
            "parameters": skinny_parameters(parameters_schema),
        },
    }


def _strip_descriptions(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: _strip_descriptions(value)
            for key, value in node.items()
            if key != "description"
        }
    if isinstance(node, list):
        return [_strip_descriptions(item) for item in node]
    return node
