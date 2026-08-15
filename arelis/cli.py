from __future__ import annotations

import asyncio
import sys
from typing import Any

from arelis.config import load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm import (
    build_router,
    run_auto_lessons,
    run_model_preflight,
    run_model_warmup,
)
from arelis.memory import MemoryStore
from arelis.tools import build_tool_registry
from arelis.voice import VoiceService
from arelis.workspace import WorkspaceRoots, compose_stt_initial_prompt


class CliPrinter:
    """Renders bus events to the terminal.

    Answers go to stdout and everything else to stderr, so `arelis --cli` can be
    piped and still produce a clean transcript.

    interactive decides whether writes are gated. On a terminal the user is
    asked, the same as in the desktop app. When stdin is a pipe there is nobody
    to ask — absence of a human is not consent, so confirms are skipped
    (denied) unless allow_write=True (`arelis --cli --allow-write`).
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        interactive: bool | None = None,
        allow_write: bool = False,
    ) -> None:
        self.bus = bus
        self._streaming = False
        self.interactive = sys.stdin.isatty() if interactive is None else interactive
        self.allow_write = bool(allow_write)
        bus.subscribe(None, self.on_event)

    async def on_event(self, event: Event) -> None:
        t = event.type
        p = event.payload
        if t == EventType.ASSISTANT_DELTA:
            if not self._streaming:
                sys.stdout.write("\nArelis: ")
                self._streaming = True
            sys.stdout.write(p.get("text", ""))
            sys.stdout.flush()
        elif t == EventType.ASSISTANT_RETRACT:
            # Already-printed characters cannot be taken back from a terminal,
            # so the retraction is explained instead of hidden.
            if self._streaming:
                sys.stdout.write("\n")
                sys.stdout.flush()
                self._streaming = False
            print("[draft withdrawn: that was a preamble to a tool call]", file=sys.stderr)
        elif t == EventType.ASSISTANT_DONE:
            if self._streaming:
                sys.stdout.write("\n")
                self._streaming = False
            else:
                text = p.get("text") or ""
                if text:
                    print(f"\nArelis: {text}")
            sys.stdout.flush()
        elif t == EventType.THINKING:
            print(f"  … {p.get('text', '')}", file=sys.stderr)
        elif t == EventType.STATUS:
            print(f"[{p.get('message', '')}]", file=sys.stderr)
        elif t == EventType.MODEL_SWITCH:
            print(
                f"[model {p.get('from')} → {p.get('to')} ({p.get('role')})]",
                file=sys.stderr,
            )
        elif t == EventType.ERROR:
            print(f"\nError: {p.get('message')}", file=sys.stderr)
            self._streaming = False
        elif t == EventType.TOOL_RESULT:
            print(f"[tool {p.get('tool')} ok={p.get('ok')}]", file=sys.stderr)
        elif t == EventType.TOOL_CONFIRM:
            decision, allow_turn = await self._decide(str(p.get("summary") or ""))
            await self.bus.publish(
                Event(
                    EventType.TOOL_CONFIRM_REPLY,
                    {"id": p.get("id"), "decision": decision, "allow_turn": allow_turn},
                )
            )
        elif t == EventType.TOOL_START:
            print(f"[tool start {p.get('tool')}]", file=sys.stderr)

    async def _decide(self, summary: str) -> tuple[str, bool]:
        """Ask about a write, or deny when nobody can answer (unless allow_write).

        The prompt runs in a worker thread so the event loop keeps turning: the
        agent loop is parked on this reply, but cancel and the rest of the bus
        must stay live while the terminal waits for a keystroke.
        """
        if not self.interactive:
            if self.allow_write:
                print(
                    f"[confirm auto-allowed via --allow-write] {summary}",
                    file=sys.stderr,
                )
                return "allow", False
            print(
                f"[confirm denied, stdin is not a terminal; "
                f"pass --allow-write to opt in] {summary}",
                file=sys.stderr,
            )
            return "skip", False
        prompt = f"\nConfirm: {summary}\n  [y] allow  [n] skip  [a] allow all this turn > "
        try:
            answer = (await asyncio.to_thread(input, prompt)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            # Losing stdin mid-prompt must not be read as consent.
            print("\n[confirm aborted, skipping]", file=sys.stderr)
            return "skip", False
        if answer.startswith("a"):
            return "allow_turn", True
        if answer.startswith("y"):
            return "allow", False
        return "skip", False


async def run_cli_async(
    config: dict[str, Any] | None = None,
    *,
    allow_write: bool = False,
) -> int:
    config = config or load_config()
    workspace = WorkspaceRoots.from_config(config)
    config["_workspace"] = workspace
    stt_cfg = config.setdefault("voice", {}).setdefault("stt", {})
    stt_cfg["initial_prompt"] = compose_stt_initial_prompt(config, workspace)
    bus = EventBus()
    from arelis.core.event_audit import attach_event_audit

    attach_event_audit(bus, config)
    CliPrinter(bus, allow_write=allow_write)
    router = build_router(config)
    store = MemoryStore()
    from arelis.memory.backup import backup_memory_db

    backup_memory_db(store.path)
    restore_id = store.latest_session_id(require_messages=True)
    if restore_id:
        store.open_session(restore_id)
    else:
        store.start_session()
    tools = build_tool_registry(
        config,
        workspace,
        memory_store=store,
        provider=router.provider,
        router=router,
    )
    memory = SessionMemory(sink=store)
    if restore_id:
        memory.hydrate(store.get_messages(restore_id), summary=store.get_summary(restore_id))
    Orchestrator(bus, router, tools, config, memory, workspace=workspace)
    VoiceService(bus, _muted(config))

    bus_task = asyncio.create_task(bus.run())
    # Strong reference: a bare create_task can be collected before it runs.
    async def _startup_models() -> None:
        try:
            from arelis.presence.readiness import probe_readiness

            snap = await probe_readiness(config, router=router)
            await bus.publish(
                Event(EventType.STATUS, {"message": snap.status_line()})
            )
        except Exception:
            pass
        await run_model_preflight(bus, router.provider, config.get("models"))
        await run_model_warmup(bus, router)
        agent_cfg = config.get("agent") or {}
        await run_auto_lessons(
            bus, enabled=bool(agent_cfg.get("auto_lessons", True))
        )

    preflight_task = asyncio.create_task(_startup_models())
    print("Arelis CLI — type /help, or chat. Ctrl+C to exit.")
    print("Pronunciation: ah-REL-is\n")
    try:
        while True:
            try:
                line = await asyncio.to_thread(input, "You> ")
            except EOFError:
                break
            text = line.strip()
            if not text:
                continue
            if text in {"/exit", "/quit", "exit", "quit"}:
                break
            await bus.publish(Event(EventType.USER_MESSAGE, {"text": text}))
            # Block until the turn is fully handled before prompting again.
            # The turn's handler task stays unfinished for its whole duration,
            # so the queue's unfinished count cannot reach zero early.
            await bus.drain()
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        bus.stop()
        preflight_task.cancel()
        bus_task.cancel()
        await router.close()
    return 0


def _muted(config: dict[str, Any]) -> dict[str, Any]:
    """Turn speech output off for the CLI.

    Playback belongs to the desktop app, which owns the audio device. Leaving
    TTS on here would run Piper once per sentence and write clips nobody can
    hear. Speech input is untouched: there is no microphone control at a
    prompt, but a script publishing a transcript still works.
    """
    voice = config.get("voice", {})
    if not (voice.get("enabled") and voice.get("tts", {}).get("enabled", True)):
        return config
    print("[voice output is desktop only; the CLI stays text]", file=sys.stderr)
    muted = {**config, "voice": {**voice, "tts": {**voice.get("tts", {}), "enabled": False}}}
    return muted


def run_cli(
    config: dict[str, Any] | None = None,
    *,
    allow_write: bool = False,
) -> int:
    return asyncio.run(run_cli_async(config, allow_write=allow_write))
