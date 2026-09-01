"""Confirm phase: blocked args, skip_repeat_fail, Allow wait, deny."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from arelis.core.events import Event, EventType
from arelis.core.loop_helpers import _SKIP_NOTICE, _tool_fail_fingerprint
from arelis.core.preflight import user_asked_for_browser
from arelis.core.turn_context import TurnContext
from arelis.tools.base import confirm_args_blocked
from arelis.tools.policy import confirm_toggles_for_call

SKIP = "skip"
STOP = "stop"
RUN = "run"


async def confirm_call(
    loop: Any,
    ctx: TurnContext,
    name: str,
    args: dict[str, Any],
    *,
    text: str,
    fail_counts: dict[str, int],
    skip_counts: dict[str, int],
    messages: list[dict[str, Any]],
    tool_names: set[str],
    drop_wander: Callable[..., None],
) -> tuple[str, str, str]:
    """Decide whether to pause for Allow.

    Returns ``(action, summary, call_fp)``. ``action`` is ``skip`` (next
    call), ``stop`` (break the call loop), or ``run`` (execute).
    """
    blocked = confirm_args_blocked(name, args)
    if blocked:
        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"phase=confirm blocked  {blocked}"},
            )
        )
        messages.append(loop._tool_message(name, f"[fail:other] {blocked}"))
        loop._trace.append(f"{name} blocked: {blocked}")
        return SKIP, "", ""

    call_fp = _tool_fail_fingerprint(name, args)
    if fail_counts.get(call_fp, 0) >= 2:
        notice = (
            f"[fail:other] Already failed twice with the same "
            f"{name} arguments this turn; not asking Allow again. "
            "Change the args or stop."
        )
        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"phase=confirm skip_repeat_fail  {name}"},
            )
        )
        messages.append(loop._tool_message(name, notice))
        loop._trace.append(f"{name} skip_repeat_fail")
        # Do not rebuild ollama_tools. Changing the schema array
        # busts the prefix cache and the next round pays ~50s to
        # re-read the persona. fail_counts already drops the call.
        stop_msg = (
            f"Stop calling `{name}` with those same arguments — it "
            "already failed twice this turn."
        )
        if (
            "weather" in loop._expected_tools
            and "weather" in tool_names
            and "weather" not in loop.tools_used
        ):
            stop_msg += (
                " Call the weather tool for the forecast instead."
            )
        else:
            stop_msg += (
                " Use a different tool or answer from what you have."
            )
        messages.append({"role": "user", "content": stop_msg})
        if loop._timer is not None:
            loop._timer.mark(
                "skip_repeat_fail", tool=name, action="drop_tool"
            )
        return SKIP, "", call_fp

    needs = loop.tools.needs_confirm(
        name,
        args,
        # "allow writes this turn" covers images/files/browser/vision.
        # It deliberately does not cover mail/SMS (confirm_send) or
        # calendar mutates (agenda create/update/delete) — those
        # stay one Allow each.
        **confirm_toggles_for_call(
            name,
            confirm_writes=loop.confirm_writes,
            confirm_image=loop.confirm_image,
            confirm_send=loop.confirm_send,
            confirm_browser=loop.confirm_browser,
            confirm_vision=loop.confirm_vision,
            confirm_run=loop.confirm_run,
            allow_writes_this_turn=ctx.allow_writes_this_turn,
        ),
    )
    if name == "browser" and user_asked_for_browser(text):
        needs = False
    if (
        loop._look is not None
        and name in {"ocr", "vision"}
        and loop._look.grant_minted
    ):
        needs = False
    if (
        loop._look is not None
        and name in {"ocr", "vision"}
        and not needs
    ):
        loop._look.grant_minted = True

    summary = loop.tools.summarize_call(name, args)
    if loop._look is not None and name in {"ocr", "vision"}:
        look_path = str(args.get("path") or loop._look.path or "")
        summary = (
            f"look ({loop._look.intent.act}) at {look_path} — "
            "one still, no further actions"
        )
    if needs:
        confirm_id = uuid4().hex
        confirm_t0 = time.perf_counter()
        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"phase=confirm waiting Allow for {name}"},
            )
        )
        # Heartbeat while the card is open (L10) so wall-clock wait
        # is not mistaken for a hung model.
        heartbeat = asyncio.create_task(
            loop._confirm_wait_heartbeat(name, confirm_t0)
        )
        try:
            decision = await loop.request_confirm(
                confirm_id, name, args, summary
            )
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
        confirm_ms = int((time.perf_counter() - confirm_t0) * 1000)
        if loop._timer is not None:
            loop._timer.confirm_ms += confirm_ms
            loop._timer.mark(
                "confirm",
                tool=name,
                ms=confirm_ms,
                decision=decision,
            )
        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {
                    "text": (
                        f"phase=confirm ms={confirm_ms} "
                        f"decision={decision}"
                    )
                },
            )
        )
        if decision == "allow_turn":
            ctx.allow_writes_this_turn = True
            decision = "allow"
        if decision != "allow":
            await loop.bus.publish(
                Event(EventType.THINKING, {"text": f"skip  {summary}"})
            )
            skip_counts[call_fp] = skip_counts.get(call_fp, 0) + 1
            drop = (
                name not in loop._expected_tools
                or skip_counts[call_fp] >= 2
            )
            if drop:
                notice = (
                    f"The user declined `{name}` and it is not "
                    "available for the rest of this turn. Do not "
                    "call it again."
                )
                if (
                    "send_sms" in loop._expected_tools
                    and name != "send_sms"
                ):
                    notice += (
                        " If to and body are known, call send_sms."
                    )
                elif (
                    "send_email" in loop._expected_tools
                    and name != "send_email"
                ):
                    notice += (
                        " Call send_email if the draft is complete."
                    )
                messages.append(loop._tool_message(name, notice))
                drop_wander(name)
                loop._trace.append(f"{name} skipped and dropped")
                if loop._timer is not None:
                    loop._timer.mark(
                        "skip_drop", tool=name, action="drop_tool"
                    )
            else:
                messages.append(
                    loop._tool_message(
                        name, _SKIP_NOTICE.format(tool=name)
                    )
                )
                loop._trace.append(f"{name} declined by user")
            if (
                name in {"send_sms", "send_email"}
                and name in loop._expected_tools
            ):
                ctx.skip_finish_text = "Okay — I did not send that."
                return STOP, summary, call_fp
            return SKIP, summary, call_fp
        if loop._look is not None and name in {"ocr", "vision"}:
            loop._look.grant_minted = True
            loop._look.allow_count = 1

    return RUN, summary, call_fp
