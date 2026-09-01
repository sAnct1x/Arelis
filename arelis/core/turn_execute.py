"""Run an allowed tool: call, publish, receipts, finish gates."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from arelis.contacts import format_contact_spoken
from arelis.core.agenda_complete import looks_like_calendar_delete
from arelis.core.events import Event, EventType
from arelis.core.evidence import classify_fetch_failure
from arelis.core.fail_tags import tool_fail_replan_notice
from arelis.core.look import LOOKING_STATUS, format_see_record
from arelis.core.memory import tool_trace_entry
from arelis.core.receipts import (
    action_receipt,
    append_action_ledger,
    format_action_receipt,
)
from arelis.core.sms_complete import (
    looks_like_contact_email_ask,
    looks_like_contact_phone_ask,
    looks_like_contacts_followup,
    looks_like_contacts_utterance,
)
from arelis.core.tool_results import PreparedToolOutput, prepare_tool_output
from arelis.core.turn_context import TurnContext
from arelis.core.untrusted import frame_external_tool_output
from arelis.tools.inbox import INBOX_PEEK_ACTIONS, inbox_peek_was_empty
from arelis.tools.safety import redact_secrets, truncate_tool_output
from arelis.tools.weather import (
    weather_place_key,
    weather_places_missing,
    weather_wants_beyond_today,
)


async def execute_call(
    loop: Any,
    ctx: TurnContext,
    r: SimpleNamespace,
    name: str,
    args: dict[str, Any],
    *,
    summary: str,
    call_fp: str,
    round_i: int,
    call_i: int,
    fanout_results: dict[int, tuple[int, Any]] | None,
) -> bool:
    """Run the allowed tool and publish the result. True ends the turn."""
    text = r.text
    agent_cfg = r.agent_cfg
    available_all = r.available_all
    available = r.available
    visible = r.visible
    tool_names = r.tool_names
    sources = r.sources
    ledger = r.ledger
    fail_counts = r.fail_counts
    web_search_ok = r.web_search_ok
    page_ok = r.page_ok
    sms_sent = r.sms_sent
    agenda_created = r.agenda_created
    weather_ok_places = r.weather_ok_places
    weather_days_retried = r.weather_days_retried
    exact_need = r.exact_need
    offer_tools = r.offer_tools
    ollama_tools = r.ollama_tools
    messages = r.messages
    sms_draft = r.sms_draft
    email_draft = r.email_draft
    try:
        await loop.bus.publish(Event(EventType.TOOL_START, {"tool": name, "args": args}))
        if loop._look is not None and name == "vision":
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": LOOKING_STATUS},
                )
            )
        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"round {round_i}/{loop.max_rounds}  tool  {summary}"},
            )
        )
        if name == "image":
            ctx.image_attempted = True
        if fanout_results is not None:
            ms, result = fanout_results[call_i]
        else:
            t0 = time.perf_counter()
            result = await loop.tools.call(name, **args)
            ms = int((time.perf_counter() - t0) * 1000)
        if loop._timer is not None:
            loop._timer.tool_ms += ms
            loop._timer.tools.append(name)
            tool_fields: dict[str, Any] = {
                "name": name,
                "ms": ms,
                "ok": result.ok,
            }
            action = str(args.get("action") or "").strip()
            if action:
                tool_fields["action"] = action
            loop._timer.mark("tool", **tool_fields)
        data_dict = result.data if isinstance(result.data, dict) else None
        if name in {"scrape", "web_fetch"} and not result.ok:
            tag = ""
            if isinstance(data_dict, dict):
                tag = str(data_dict.get("fail_class") or "")
            if not tag:
                tag = classify_fetch_failure(str(result.output or ""))
            if tag == "fail:js_shell":
                url = ""
                if isinstance(data_dict, dict):
                    url = str(data_dict.get("url") or "").strip()
                if not url.startswith("http"):
                    url = str(args.get("url") or "").strip()
                if url.startswith("http"):
                    ctx.js_shell_url = url
                    if "browser" in available_all:
                        visible = set(visible) | {"browser"}
                        available = set(available) | {"browser"}
                        ctx.tool_names.clear()
                        ctx.tool_names.update(visible)
                        tool_names = ctx.tool_names
                        if offer_tools:
                            ollama_tools = loop.tools.ollama_tools(visible)
        if result.ok:
            loop.tools_used.add(name)
            fail_counts.pop(call_fp, None)
            ctx.last_ok_tool_out = str(result.output or "")
            ctx.last_ok_tool_name = name
            if name == "inbox" and str(args.get("action") or "").lower() in {
                "trash",
                "archive",
                "delete",
            }:
                ctx.inbox_mutated_ok = True
            if (
                name == "inbox"
                and str(args.get("action") or "").lower() in INBOX_PEEK_ACTIONS
                and inbox_peek_was_empty(data_dict)
            ):
                ctx.inbox_empty_ok = True
            if name == "browser":
                b_act = str(args.get("action") or "").strip().lower()
                if b_act == "snapshot":
                    ctx.last_browser_snapshot = str(result.output or "")
                if b_act == "click":
                    ctx.browser_clicked = True
            if name == "web_search":
                q = str(args.get("query") or "").strip().casefold()
                if q:
                    web_search_ok.add(q)
            if name in {"scrape", "web_fetch"}:
                page = str(args.get("url") or "").strip().casefold()
                if page:
                    page_ok.add(page)
            if name == "send_sms":
                sent_to = str(args.get("to") or "").strip()
                if sent_to:
                    sms_sent.add(sent_to)
            if name == "send_email":
                ctx.email_sent_ok = True
            if name == "agenda" and str(args.get("action") or "").lower() == "create":
                agenda_created.add(
                    f"{str(args.get('provider') or '').strip().lower()}|"
                    f"{str(args.get('summary') or '').strip().casefold()}|"
                    f"{str(args.get('start') or '').strip()}"
                )
                ctx.agenda_create_ok = True
            if loop._look is not None:
                loop._note_look_tool(name, args, result, data_dict)
        else:
            fail_counts[call_fp] = fail_counts.get(call_fp, 0) + 1
            if name == "send_sms":
                ctx.sms_failed = True
            if loop._look is not None and name == "camera":
                loop._look.camera_snaps += 1
        if (not result.ok) and (
            name == "browser"
            and data_dict
            and str(data_dict.get("code") or "") == "PROFILE_LOCKED"
        ):
            # Attempted browser counts for routing_gap (R9).
            loop.tools_used.add(name)
        resolved = None
        if data_dict:
            resolved = data_dict.get("abs_path") or data_dict.get("path")
        if name == "browser" and data_dict:
            mode = str(data_dict.get("mode") or "").strip()
            code = str(data_dict.get("code") or "").strip()
            bits = ["browser"]
            if mode:
                bits.append(mode)
            if code:
                bits.append(code)
            action = str(args.get("action") or "").strip()
            if action:
                bits.append(action)
            await loop.bus.publish(
                Event(EventType.THINKING, {"text": "  ".join(bits)})
            )
            if (
                code
                in {
                    "PROFILE_LOCKED",
                    "RELAUNCH_FAILED",
                    "CDP_TIMEOUT",
                    "CDP_DEAD",
                }
                and not ctx.browser_relaunch_nudge_used
                and bool(agent_cfg.get("browser_relaunch_force", True))
            ):
                ctx.browser_relaunch_nudge_used = True
                pending_url = str(
                    args.get("url") or args.get("target") or ""
                ).strip()
                url_bit = (
                    f", url={pending_url!r}" if pending_url else ""
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Browser connect/control failed "
                            f"({code}). If the user only asked to "
                            "pull up a site, call browser(action=open"
                            f"{url_bit}) — that is a plain OS open "
                            "(no Chrome restart). For click/snapshot/"
                            "navigate when CDP is down, call "
                            f"browser(action=relaunch{url_bit}) after "
                            "Allow, or ask them to close extra Chrome "
                            "windows. Do not screenshot until connected."
                        ),
                    }
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {
                            "text": (
                                f"browser {code}; one-shot "
                                "relaunch-then-open nudge"
                            )
                        },
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness", gate="browser_relaunch", action="nudge"
                    )
        loop._trace.append(
            tool_trace_entry(name, args, result.ok, resolved_path=resolved)
        )
        ledger.record_tool(
            name,
            ok=result.ok,
            output=str(result.output or ""),
            data=data_dict,
            args=args if isinstance(args, dict) else None,
        )
        receipt = action_receipt(
            name,
            ok=result.ok,
            args=args if isinstance(args, dict) else None,
            data=data_dict,
        )
        if loop._look is not None and name in {"vision", "ocr", "camera"}:
            receipt = None
            loop._emit_look_receipt_if_ready()
        if receipt is not None:
            loop._receipts.append(receipt)
            receipt_line = format_action_receipt(receipt)
            loop._trace.append(receipt_line)
            if loop._timer is not None:
                loop._timer.mark(
                    "receipt",
                    action=str(receipt.get("action") or name),
                    ok=True,
                )
            await loop.bus.publish(
                Event(EventType.THINKING, {"text": receipt_line})
            )
            session_id = None
            sink = getattr(loop.memory, "sink", None)
            if sink is not None:
                session_id = getattr(sink, "session_id", None)
            append_action_ledger(receipt, session_id=session_id)

        if (
            name in {"web_fetch", "scrape"}
            or (
                name == "browser"
                and result.ok
                and str(args.get("action") or "").strip().lower() == "read"
            )
        ) and result.ok:
            url = str(
                (data_dict or {}).get("url") or args.get("url") or ""
            ).strip()
            if (
                (url.startswith("http://") or url.startswith("https://"))
                and all(url != known for _, known in sources)
            ):
                title = str((data_dict or {}).get("title") or "").strip()
                sources.append((title, url))
        if name == "research_report" and result.ok and data_dict:
            for item in data_dict.get("sources") or []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not (
                    url.startswith("http://") or url.startswith("https://")
                ):
                    continue
                if any(url == known for _, known in sources):
                    continue
                title = str(item.get("title") or "").strip()
                sources.append((title, url))

        # Redact → optional fat-tool summary card → hard char cap.
        redacted = redact_secrets(result.output)
        if bool(agent_cfg.get("tool_summary_inject", True)):
            prepared = prepare_tool_output(
                name,
                redacted,
                data=data_dict,
                max_inject_chars=min(loop.tool_output_chars, 4000),
                force=False,
            )
        else:
            prepared = PreparedToolOutput(
                inject=redacted,
                full_ref=None,
                summarized=False,
                original_chars=len(redacted),
            )
        if prepared.summarized:
            if loop._timer is not None:
                loop._timer.mark(
                    "tool_summary",
                    tool=name,
                    orig=prepared.original_chars,
                    ref=prepared.full_ref or "-",
                )
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {
                        "text": (
                            f"tool_summary  {name}  "
                            f"{prepared.original_chars} chars → card"
                            + (
                                f"  ref={prepared.full_ref}"
                                if prepared.full_ref
                                else ""
                            )
                        )
                    },
                )
            )
            if data_dict is not None and prepared.full_ref:
                data_dict = {**data_dict, "full_ref": prepared.full_ref}
        out, trunc = truncate_tool_output(
            prepared.inject, loop.tool_output_chars
        )
        out = frame_external_tool_output(
            name,
            out,
            action=str(args.get("action") or "")
            if isinstance(args, dict)
            else "",
        )
        if (
            loop._look is not None
            and name in {"ocr", "vision"}
            and loop._look.record is not None
            and result.ok
        ):
            out = f"{out}\n\n{format_see_record(loop._look.record)}"
        if trunc.truncated:
            if loop._timer is not None:
                loop._timer.mark(
                    "truncate",
                    tool=name,
                    orig=trunc.original_chars,
                    kept=trunc.kept_chars,
                )
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {
                        "text": (
                            f"truncated  {name}  "
                            f"{trunc.original_chars}->{trunc.kept_chars} chars"
                        )
                    },
                )
            )
        await loop.bus.publish(
            Event(
                EventType.TOOL_RESULT,
                {
                    "tool": name,
                    "ok": result.ok,
                    "output": out,
                    "data": result.data,
                    "truncated": trunc.truncated,
                    "original_chars": trunc.original_chars,
                    "kept_chars": trunc.kept_chars,
                },
            )
        )
        if name == "browser" and data_dict:
            wall_code = str(data_dict.get("code") or "")
            if wall_code in {"YOUR_TURN", "SECRET_FIELD"}:
                await loop.bus.publish(
                    Event(
                        EventType.TURN_PAUSE,
                        {
                            "reason": "your_turn",
                            "kind": str(
                                data_dict.get("wall")
                                or ("login" if wall_code == "SECRET_FIELD" else "")
                            ),
                        },
                    )
                )
                await loop._await_your_turn(
                    str(data_dict.get("wall") or "")
                )
        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {
                    "text": (
                        f"round {round_i}/{loop.max_rounds}  "
                        f"{'ok' if result.ok else 'fail'}  {name}  {ms}ms"
                    )
                },
            )
        )
        if (
            name in {"image", "image_edit"}
            and result.ok
            and data_dict
            and data_dict.get("path")
        ):
            await loop.bus.publish(
                Event(EventType.IMAGE_READY, {"path": data_dict["path"]})
            )
            # Finish now — otherwise the 7B often re-calls image and
            # spams Allow (same class of bug as double-SMS). image_edit
            # joins it because the round after a finished edit is where
            # she reached for vision to check her own work and then the
            # calculator to verify the pixel count.
            path = str(data_dict["path"])
            if name == "image_edit":
                # Its own sentence already names the sizes and the
                # adjustments, which is the part worth reading.
                await loop._finish(str(result.output).strip(), sources, streamed="")
                return True
            await loop._finish(
                f"Image ready — open in Workspace ({path}).",
                sources,
                streamed="",
            )
            return True
        if (
            name in {"document", "plot"}
            and result.ok
            and data_dict
            and data_dict.get("abs_path")
        ):
            await loop.bus.publish(
                Event(
                    EventType.FILE_READY,
                    {
                        "path": str(data_dict.get("path") or ""),
                        "abs_path": str(data_dict.get("abs_path") or ""),
                        "format": str(data_dict.get("format") or ""),
                        "title": str(data_dict.get("title") or ""),
                        "show_card": True,
                        "open": False,
                    },
                )
            )
        if (
            name == "schedule"
            and result.ok
            and str(args.get("action") or "").lower()
            in {"create", "create_briefing"}
        ):
            # Keep [job.id] in the transcript. The 7B otherwise
            # paraphrases the tool output and the id vanishes.
            await loop._finish(str(result.output).strip(), sources, streamed="")
            return True
        messages.append(loop._tool_message(name, out))
        if (
            name == "schedule"
            and result.ok
            and str(args.get("action") or "").lower() in {"list", "delete"}
        ):
            ctx.schedule_managed_ok = True
        # Successful weather → answer from it; do not re-fetch all round.
        # days=1 is today only; if they asked tomorrow, one retry with
        # days=3. fill_weather_args usually bumps that before the call.
        # Two named cities are two readings; lock per place, not the tool.
        if name == "weather" and result.ok:
            used_days = 3
            try:
                used_days = int(args.get("days") or 3)
            except (TypeError, ValueError):
                used_days = 3
            wx_key = weather_place_key(str(args.get("place") or ""))
            retry_days = (
                used_days < 2
                and weather_wants_beyond_today(text)
                and wx_key not in weather_days_retried
            )
            if retry_days:
                weather_days_retried.add(wx_key)
                keep_place = str(args.get("place") or "").strip()
                retry_msg = (
                    "That reading is today only. Call weather "
                    "again with days=3 (keep place if you used "
                    "one). Then answer the user from that."
                )
                if keep_place:
                    retry_msg = (
                        "That reading is today only. Call weather "
                        f"again with days=3 and place={keep_place}. "
                        "Then answer the user from that."
                    )
                messages.append(
                    {
                        "role": "user",
                        "content": retry_msg,
                    }
                )
            else:
                weather_ok_places.add(wx_key)
                missing = weather_places_missing(text, weather_ok_places)
                if missing:
                    nxt = missing[0]
                    if nxt:
                        more_msg = (
                            "You already have a successful weather "
                            f"reading this turn. Call weather now with "
                            f"place={nxt} and days=3 for the other city. "
                            "Then answer from every reading. Do not "
                            "skip a named city."
                        )
                    else:
                        more_msg = (
                            "You already have a successful weather "
                            "reading this turn. Call weather now "
                            "without place for the user's own location. "
                            "Then answer from every reading."
                        )
                    messages.append(
                        {"role": "user", "content": more_msg}
                    )
                else:
                    # Keep the tool array byte-stable. Stripping weather
                    # here used to re-prefill the whole 23k prefix (~50s)
                    # for "answer from the reading you already have."
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "You already have a successful weather tool "
                                "result this turn. Answer the user now in plain "
                                "prose from that reading. Do not call weather "
                                "again."
                            ),
                        }
                    )
            if loop._timer is not None:
                loop._timer.mark(
                    "weather_once",
                    action=(
                        "retry_days"
                        if retry_days
                        else (
                            "need_place"
                            if weather_places_missing(text, weather_ok_places)
                            else "answer_now"
                        )
                    ),
                )
        # Successful SMS to every draft recipient → confirm and stop.
        # Otherwise the model re-opens Allow and double-texts.
        if (
            name == "send_sms"
            and result.ok
            and sms_draft is not None
            and sms_draft.complete
        ):
            sent_l = {s.lower() for s in sms_sent}
            still = [
                a
                for a in (sms_draft.resolved_aliases or sms_draft.all_tos)
                if a and a.lower() not in sent_l
            ]
            if not still:
                who = ", ".join(sms_draft.all_tos) or "them"
                await loop._finish(
                    f"Sent your text to {who}.",
                    sources,
                    streamed="",
                )
                return True
        if (
            name == "send_email"
            and result.ok
            and email_draft is not None
            and email_draft.complete
        ):
            who = email_draft.tool_to or email_draft.to or "them"
            await loop._finish(
                f"Sent email to {who}.",
                sources,
                streamed="",
            )
            return True
        if (
            name == "contacts"
            and result.ok
            and "send_sms" not in loop._expected_tools
            and (
                looks_like_contacts_utterance(text)
                or looks_like_contacts_followup(
                    text, loop.memory.messages
                )
                or "contacts" in loop._expected_tools
            )
        ):
            data = result.data if isinstance(result.data, dict) else {}
            if looks_like_contact_phone_ask(text):
                field = "phone"
            elif looks_like_contact_email_ask(text):
                field = "email"
            else:
                field = "who"
            spoken = format_contact_spoken(data, field=field)
            await loop._finish(
                spoken or out.strip() or "No contact matched.",
                sources,
                streamed="",
            )
            return True
        # A store listing is already the answer, so handing it back beats
        # letting the 7B paraphrase a list it will pad. Only once nothing
        # else is outstanding, though: "what are my deadlines? pack my
        # week" expects tasks *and* agenda, and finishing on tasks meant
        # the calendar half of the ask was silently dropped.
        if (
            name in {"tasks", "goals"}
            and result.ok
            and name in loop._expected_tools
            and not (loop._expected_tools - loop.tools_used - {name})
        ):
            await loop._finish(
                out.strip() or f"{name} done.",
                sources,
                streamed="",
            )
            return True
        if (
            name == "agenda"
            and result.ok
            and looks_like_calendar_delete(text)
            and str(args.get("action") or "").strip().lower() == "delete"
        ):
            await loop._finish(
                out.strip() or "Calendar delete finished.",
                sources,
                streamed="",
            )
            return True
        if (
            not result.ok
            and not loop._fail_replan_used
        ):
            replan = tool_fail_replan_notice(
                name, redacted, ok=False
            )
            if (
                replan
                and name == "web_search"
                and (
                    exact_need.needs_weather
                    or "weather" in loop._expected_tools
                )
            ):
                replan += (
                    " If they asked about the weather/forecast, call "
                    "weather — do not web_search again."
                )
            if replan:
                loop._fail_replan_used = True
                if loop._timer is not None:
                    loop._timer.mark("fail_replan", tool=name)
                messages.append({"role": "system", "content": replan})
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"fail_replan  {name}"},
                    )
                )
    finally:
        r.available = available
        r.visible = visible
        r.tool_names = tool_names
        r.ollama_tools = ollama_tools
    return False
