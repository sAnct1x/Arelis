"""One constructor for the attended / CLI / job brain.

UI, CLI, jobs, and the tray-restore harness used to each bind workspace, bus,
router, tools, memory, and Orchestrator by hand. Session policy already
drifted (glass vs last-thread vs ephemeral). A single ``profile`` knob keeps
those product differences explicit instead of forked copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from arelis.config import load_config
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm import build_router
from arelis.llm.router import ModelRouter
from arelis.memory import MemoryStore
from arelis.tools import build_tool_registry
from arelis.tools.base import ToolRegistry
from arelis.workspace import WorkspaceRoots, compose_stt_initial_prompt

SeatProfile = Literal["ui", "cli", "job", "verify_tray"]


@dataclass
class AgentSeat:
    config: dict[str, Any]
    workspace: WorkspaceRoots
    bus: EventBus
    router: ModelRouter
    tools: ToolRegistry
    memory: SessionMemory
    orchestrator: Orchestrator
    store: MemoryStore | None
    restore_id: str | None = None


def bind_workspace(config: dict[str, Any], *, stt_prompt: bool = True) -> WorkspaceRoots:
    """Shared WorkspaceRoots on the config, and optionally the STT jargon seed."""
    workspace = WorkspaceRoots.from_config(config)
    config["_workspace"] = workspace
    if stt_prompt:
        stt = config.setdefault("voice", {}).setdefault("stt", {})
        stt["initial_prompt"] = compose_stt_initial_prompt(config, workspace)
    return workspace


def build_seat(
    config: dict[str, Any] | None = None,
    *,
    profile: SeatProfile,
    bus: EventBus | None = None,
) -> AgentSeat:
    """Assemble the brain for one entry point. Callers still own Qt, voice, warmup."""
    config = config or load_config()
    workspace = bind_workspace(config, stt_prompt=profile != "job")
    if bus is None:
        bus = EventBus()
    if profile in {"ui", "cli"}:
        from arelis.core.event_audit import attach_event_audit

        attach_event_audit(bus, config)

    router = build_router(config)
    store: MemoryStore | None = None
    restore_id: str | None = None
    allow_send = profile != "job"

    if profile == "job":
        memory = SessionMemory()
        tools = build_tool_registry(config, workspace, allow_send=False)
        orchestrator = Orchestrator(
            bus, router, tools, config, memory, workspace=workspace
        )
        return AgentSeat(
            config=config,
            workspace=workspace,
            bus=bus,
            router=router,
            tools=tools,
            memory=memory,
            orchestrator=orchestrator,
            store=None,
        )

    store = MemoryStore()
    if profile == "ui":
        store.start_glass_session()
    elif profile == "cli":
        from arelis.memory.backup import backup_memory_db

        backup_memory_db(store.path)
        restore_id = store.latest_session_id(require_messages=True)
        if restore_id:
            store.open_session(restore_id)
        else:
            store.start_session()
    else:
        store.start_session()

    tools = build_tool_registry(
        config,
        workspace,
        allow_send=allow_send,
        memory_store=store,
        provider=router.provider,
        router=router,
    )
    if profile == "verify_tray":
        memory = SessionMemory(sink=store)
    else:
        memory = SessionMemory.from_config(config, sink=store)
        if profile == "cli" and restore_id:
            memory.hydrate(
                store.get_messages(restore_id),
                summary=store.get_summary(restore_id),
            )
    orchestrator = Orchestrator(
        bus, router, tools, config, memory, workspace=workspace
    )
    return AgentSeat(
        config=config,
        workspace=workspace,
        bus=bus,
        router=router,
        tools=tools,
        memory=memory,
        orchestrator=orchestrator,
        store=store,
        restore_id=restore_id,
    )
