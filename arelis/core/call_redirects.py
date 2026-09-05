"""Wander-redirect table for ``dispatch_calls``.

First match wins, same as the original if/elif chain. A step returns
``None`` to skip, ``(\"skip\",)`` to drop this call, or
``(\"run\", name, args)`` to execute a replacement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from arelis.core.agenda_complete import (
    agenda_force_call_notice,
    agenda_read_action,
    draft_agenda_create_args,
    draft_agenda_delete_args,
    looks_like_calendar_close,
    looks_like_calendar_delete,
    looks_like_calendar_open,
    looks_like_calendar_read,
)
from arelis.core.agent_loop import (
    _BROWSER_WANDER,
    _LOCAL_STORE,
    _SMS_WANDER,
    _WEATHER_WANDER,
    should_redirect_wander_to_sms,
)
from arelis.core.claims import local_store_inject_args
from arelis.core.email_complete import (
    draft_send_email_args,
    email_remaining,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
)
from arelis.core.events import Event, EventType
from arelis.core.intent_catalog import (
    EARTH_STATUS,
    RUN_SCRIPT,
    SOLAR_STATUS,
    earth_status_action,
    run_script_path,
    solar_status_action,
)
from arelis.core.preflight import draft_browser_args
from arelis.core.sms_complete import draft_send_sms_args, looks_like_browser_or_url
from arelis.core.tile_complete import match_tile_intent, tile_tool_args
from arelis.core.turn_context import TurnContext
from arelis.tools.weather import draft_weather_args, weather_places_missing

RedirectFn = Callable[..., Awaitable[tuple[Any, ...] | None]]


async def _think(loop: Any, text: str) -> None:
    await loop.bus.publish(Event(EventType.THINKING, {"text": text}))


async def redirect_weather(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    if not (
        name in _WEATHER_WANDER
        and bool(r.agent_cfg.get("weather_force_call", True))
        and r.exact_need.needs_weather
        and not looks_like_scheduled_send(r.text)
        and not looks_like_schedule_manage(r.text)
        and not ctx.schedule_managed_ok
        and weather_places_missing(r.text, r.weather_ok_places)
        and "weather" in r.tool_names
    ):
        return None
    notice = f"Blocked: this turn expects the weather tool, not {name}. Call weather now."
    await _think(loop, f"redirect  {name} → weather")
    r.messages.append(loop._tool_message(name, notice))
    drop_wander(*_WEATHER_WANDER)
    inj = draft_weather_args(r.text)
    missing = weather_places_missing(r.text, r.weather_ok_places)
    if missing:
        if missing[0]:
            inj["place"] = missing[0]
        else:
            inj.pop("place", None)
    await _think(loop, "inject  weather from intent")
    if loop._timer is not None:
        loop._timer.mark("exactness", gate="weather_redirect", action="inject")
    return ("run", "weather", inj)


async def redirect_browser_to_agenda(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    if not (name == "browser" and looks_like_calendar_open(r.text) and "agenda" in r.tool_names):
        return None
    notice = (
        "Blocked: this turn expects the Arelis calendar tile, "
        f"not {name}. Call agenda with action=open."
    )
    await _think(loop, "redirect  browser → agenda")
    r.messages.append(loop._tool_message(name, notice))
    await _think(loop, "inject  agenda open from intent")
    if loop._timer is not None:
        loop._timer.mark("exactness", gate="agenda_redirect", action="inject")
    return ("run", "agenda", {"action": "open"})


async def redirect_browser_to_solar(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    if not (name == "browser" and SOLAR_STATUS.matches(r.text) and "solar" in r.tool_names):
        return None
    inj = {"action": solar_status_action(r.text)}
    notice = (
        "Blocked: this turn expects the solar lab, "
        f"not {name}. Call solar with action={inj['action']}."
    )
    await _think(loop, "redirect  browser → solar")
    r.messages.append(loop._tool_message(name, notice))
    return ("run", "solar", inj)


async def redirect_browser_to_earth(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    if not (name == "browser" and EARTH_STATUS.matches(r.text) and "earth" in r.tool_names):
        return None
    inj = {"action": earth_status_action(r.text)}
    notice = (
        "Blocked: this turn expects the Earth zone, "
        f"not {name}. Call earth with action={inj['action']}."
    )
    await _think(loop, "redirect  browser → earth")
    r.messages.append(loop._tool_message(name, notice))
    return ("run", "earth", inj)


async def redirect_python_to_run_script(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    if not (
        name == "python"
        and RUN_SCRIPT.matches(r.text)
        and "run_script" in r.tool_names
        and "run_script" not in loop.tools_used
    ):
        return None
    path = run_script_path(r.text)
    if not path:
        return None
    notice = (
        "Blocked: they named a .py to run. "
        f"Call run_script with path={path}, not the python cell."
    )
    await _think(loop, "redirect  python → run_script")
    r.messages.append(loop._tool_message(name, notice))
    return ("run", "run_script", {"path": path})


async def redirect_browser_to_tile(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    if not (name == "browser" and match_tile_intent(r.text) and "tile" in r.tool_names):
        return None
    from arelis.tools.tile import TileTool

    inj = tile_tool_args(r.text, last_name=TileTool.last_name)
    if not inj:
        return None
    notice = (
        "Blocked: this turn expects an Arelis tile, "
        f"not {name}. Call tile with action="
        f"{inj['action']} and name={inj['name']}."
    )
    await _think(loop, "redirect  browser → tile")
    r.messages.append(loop._tool_message(name, notice))
    await _think(loop, "inject  tile from intent")
    return ("run", "tile", inj)


async def redirect_browser_wander(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    if not (
        name in _BROWSER_WANDER
        and ("browser" in loop._expected_tools or looks_like_browser_or_url(r.text))
        and not looks_like_calendar_open(r.text)
        and not looks_like_calendar_close(r.text)
        and not match_tile_intent(r.text)
        and not SOLAR_STATUS.matches(r.text)
        and not EARTH_STATUS.matches(r.text)
        and "browser" not in loop.tools_used
        and "browser" in r.tool_names
    ):
        return None
    inj = draft_browser_args(r.text)
    notice = f"Blocked: this turn expects the browser tool, not {name}. Call browser now."
    await _think(loop, f"redirect  {name} → browser")
    r.messages.append(loop._tool_message(name, notice))
    drop_wander(*_BROWSER_WANDER)
    await _think(loop, "inject  browser from intent")
    if loop._timer is not None:
        loop._timer.mark("exactness", gate="browser_redirect", action="inject")
    return ("run", "browser", inj)


async def redirect_local_store(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    if not (
        name in {"weather", "web_search", "browser", "scrape", "web_fetch", "user_location"}
        and loop._expected_tools & _LOCAL_STORE
        and name not in loop._expected_tools
    ):
        return None
    target = next(
        (
            t
            for t in ("tasks", "goals", "contacts", "memory")
            if t in loop._expected_tools and t in r.tool_names
        ),
        "",
    )
    if not (target and target not in loop.tools_used):
        return None
    notice = f"Blocked: this turn expects {target}, not {name}."
    await _think(loop, f"redirect  {name} → {target}")
    r.messages.append(loop._tool_message(name, notice))
    drop_wander("weather", "web_search", "browser", "scrape", "web_fetch", "user_location")
    inj = local_store_inject_args(
        target, r.text, receipts=loop._receipts, history=loop.memory.messages
    )
    await _think(loop, f"inject  {target} from intent")
    return ("run", target, inj)


async def redirect_sms(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    sms_draft = r.sms_draft
    if not (
        (
            should_redirect_wander_to_sms(
                name,
                loop._expected_tools,
                tools_used=loop.tools_used,
                sms_failed=ctx.sms_failed,
            )
            or (
                name == "contacts"
                and not ctx.sms_failed
            )
        )
        and "send_sms" in loop._expected_tools
        and "send_sms" not in loop.tools_used
        and not ctx.sms_failed
    ):
        return None
    notice = (
        "Blocked: this turn expects send_sms (or asking once "
        f"for the message body), not {name}. Do not invent "
        "a body. Call send_sms when to+body are known."
    )
    await _think(loop, f"redirect  {name} → sms")
    r.messages.append(loop._tool_message(name, notice))
    drop_wander(*_SMS_WANDER)
    if sms_draft is not None and sms_draft.complete and "send_sms" in r.tool_names:
        from arelis.core.turn_goal import sms_body_serves_goal

        inj = draft_send_sms_args(sms_draft, already_sent=r.sms_sent)
        if sms_body_serves_goal(str(inj.get("body") or "")):
            await _think(loop, "inject  send_sms from draft")
            if loop._timer is not None:
                loop._timer.mark("exactness", gate="sms_redirect", action="inject")
            return ("run", "send_sms", inj)
        await _think(loop, "goal unlock  sms body is not for the recipient")
    r.messages.append(
        {
            "role": "user",
            "content": (
                "The user wants to send a text. If the body is "
                "missing, ask once what to say. If to and body "
                "are known, call send_sms. Do not web_search."
            ),
        }
    )
    if loop._timer is not None:
        loop._timer.mark("exactness", gate="sms_redirect", action="block")
    return ("skip",)


async def redirect_email(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    email_draft = r.email_draft
    if not (
        name in {"web_search", "analyze"}
        and "send_email" in loop._expected_tools
        and (
            "send_email" not in loop.tools_used
            or (
                email_draft is not None
                and email_draft.complete
                and email_remaining(email_draft, ctx.email_sent)
            )
        )
        and "analyze" not in loop._expected_tools
    ):
        return None
    notice = (
        f"Blocked: this turn expects send_email, not {name}. "
        "Use the literal address the user gave."
    )
    await _think(loop, f"redirect  {name} → email")
    r.messages.append(loop._tool_message(name, notice))
    drop_wander("web_search")
    if email_draft is not None and email_draft.complete and "send_email" in r.tool_names:
        inj = draft_send_email_args(email_draft, already_sent=ctx.email_sent)
        await _think(loop, "inject  send_email from draft")
        if loop._timer is not None:
            loop._timer.mark("exactness", gate="email_redirect", action="inject")
        return ("run", "send_email", inj)
    r.messages.append(
        {
            "role": "user",
            "content": (
                "Call send_email with the address and body the user gave. "
                "Do not web_search."
            ),
        }
    )
    if loop._timer is not None:
        loop._timer.mark("exactness", gate="email_redirect", action="block")
    return ("skip",)


async def redirect_agenda(
    loop: Any, ctx: TurnContext, r: Any, name: str, args: dict[str, Any], drop_wander: Any
) -> tuple[Any, ...] | None:
    if not (
        name in {"web_search", "contacts", "user_location", "weather", "schedule"}
        and "agenda" in loop._expected_tools
        and not ctx.agenda_create_ok
    ):
        return None
    await _think(loop, f"redirect  {name} → agenda")
    r.messages.append(
        loop._tool_message(
            name,
            "Blocked: this turn expects agenda, not "
            f"{name}. Call agenda (open, close, list, create, or delete).",
        )
    )
    drop_wander("web_search", "contacts", "user_location", "weather", "schedule")
    text = r.text
    if looks_like_calendar_delete(text) and "agenda" in r.tool_names:
        inj = draft_agenda_delete_args(
            text, receipts=loop._receipts, history=loop.memory.messages
        )
        await _think(loop, "inject  agenda delete")
        if loop._timer is not None:
            loop._timer.mark("exactness", gate="agenda_redirect", action="inject")
        return ("run", "agenda", inj)
    if r.agenda_draft is not None and r.agenda_draft.complete and "agenda" in r.tool_names:
        inj = draft_agenda_create_args(r.agenda_draft)
        await _think(loop, "inject  agenda create from draft")
        if loop._timer is not None:
            loop._timer.mark("exactness", gate="agenda_redirect", action="inject")
        return ("run", "agenda", inj)
    if looks_like_calendar_close(text) and "agenda" in r.tool_names:
        await _think(loop, "inject  agenda close from intent")
        if loop._timer is not None:
            loop._timer.mark("exactness", gate="agenda_redirect", action="inject")
        return ("run", "agenda", {"action": "close"})
    if looks_like_calendar_open(text) and "agenda" in r.tool_names:
        await _think(loop, "inject  agenda open from intent")
        if loop._timer is not None:
            loop._timer.mark("exactness", gate="agenda_redirect", action="inject")
        return ("run", "agenda", {"action": "open"})
    if looks_like_calendar_read(text) and "agenda" in r.tool_names:
        await _think(loop, "inject  agenda read from intent")
        if loop._timer is not None:
            loop._timer.mark("exactness", gate="agenda_redirect", action="inject")
        return ("run", "agenda", {"action": agenda_read_action(text)})
    r.messages.append(
        {
            "role": "user",
            "content": (
                agenda_force_call_notice(r.agenda_draft)
                if r.agenda_draft is not None and r.agenda_draft.complete
                else (
                    "Call agenda with action=open, close, today, "
                    "tomorrow, list, create, or delete. Do not "
                    "web_search."
                )
            ),
        }
    )
    if loop._timer is not None:
        loop._timer.mark("exactness", gate="agenda_redirect", action="block")
    return ("skip",)


REDIRECT_STEPS: tuple[RedirectFn, ...] = (
    redirect_weather,
    redirect_browser_to_agenda,
    redirect_browser_to_solar,
    redirect_browser_to_earth,
    redirect_browser_to_tile,
    redirect_python_to_run_script,
    redirect_browser_wander,
    redirect_local_store,
    redirect_sms,
    redirect_email,
    redirect_agenda,
)


async def apply_redirects(
    loop: Any,
    ctx: TurnContext,
    r: Any,
    name: str,
    args: dict[str, Any],
    drop_wander: Any,
) -> tuple[Any, ...]:
    """Return ``(\"run\", name, args)`` or ``(\"skip\",)``."""
    for step in REDIRECT_STEPS:
        hit = await step(loop, ctx, r, name, args, drop_wander)
        if hit is not None:
            return hit
    return ("run", name, args)
