from __future__ import annotations

from pathlib import Path
from typing import Any

from arelis.llm.ollama import OllamaProvider
from arelis.llm.router import ModelRouter
from arelis.location import build_location
from arelis.mail import Mailer, load_account
from arelis.memory import MemoryStore
from arelis.memory.indexer import DEFAULT_EMBED_MODEL
from arelis.paths import user_data_dir
from arelis.rooms import RoomStore
from arelis.sms import DEFAULT_MAX_BODY_CHARS
from arelis.sms_android import AndroidSmsProvider, load_sms_account
from arelis.tools.agenda import AgendaTool
from arelis.tools.analyze import AnalyzeTool
from arelis.tools.base import ToolRegistry
from arelis.tools.browser_tool import BrowserTool
from arelis.tools.calculator import CalculatorTool
from arelis.tools.camera_capture import CameraTool
from arelis.tools.clipboard import ClipboardTool
from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.tools.contacts_tool import ContactsTool
from arelis.tools.doc_extract import DocExtractTool
from arelis.tools.email_send import SendEmailTool
from arelis.tools.git_info import GitInfoTool
from arelis.tools.goals import GoalsTool
from arelis.tools.image import ImageTool
from arelis.tools.image_edit import ImageEditTool
from arelis.tools.image_io import DEFAULT_MAX_EDGE
from arelis.tools.inbound_sms import InboundSmsTool
from arelis.tools.inbox import InboxTool
from arelis.tools.memory_tool import MemoryTool
from arelis.tools.ocr import OcrTool
from arelis.tools.recall import RecallTool
from arelis.tools.research_report import ResearchReportTool
from arelis.tools.rooms_tool import RoomsTool
from arelis.tools.schedule_jobs import ScheduleTool
from arelis.tools.scrape import ScrapeTool
from arelis.tools.search import build_search_tool
from arelis.tools.sms_send import SendSmsTool
from arelis.tools.tasks import TasksTool
from arelis.tools.user_location import UserLocationTool
from arelis.tools.vision import VisionTool
from arelis.tools.weather import WeatherTool
from arelis.tools.web import WebFetchTool
from arelis.workspace import WorkspaceRoots


def build_tool_registry(
    config: dict[str, Any],
    workspace: WorkspaceRoots | None = None,
    *,
    allow_send: bool = True,
    memory_store: MemoryStore | None = None,
    provider: OllamaProvider | None = None,
    router: ModelRouter | None = None,
) -> ToolRegistry:
    """Assemble the tools this config enables.

    Every registered tool is offered to the model, so a tool disabled here is
    genuinely unavailable rather than merely discouraged. The workspace tool is
    always registered: without file access most of what Arelis is for stops
    working, and its write actions are already behind the confirm gate.

    Pass the same WorkspaceRoots instance the orchestrator and UI hold so the
    active project stays shared.

    allow_send=False leaves send_email and send_sms out. The scheduled job
    runner uses it: nobody is watching at 7pm to read a confirm card, so the
    answer is to give the model no way to send rather than a rule telling it
    not to. The runner mails the finished answer itself.

    memory_store is the same archive SessionMemory writes through in the UI and
    CLI. Archive tools (recall, memory) are registered only when a person is
    present (allow_send=True) or when a store is passed in explicitly. The job
    runner passes neither, so an unattended turn cannot search chat or write
    facts into an emailed digest.
    """
    registry = ToolRegistry()
    workspace = workspace or WorkspaceRoots.from_config(config)
    tools_cfg = config.get("tools", {})
    agent_cfg = config.get("agent", {})
    web_cfg = tools_cfg.get("web", {})
    scrape_cfg = tools_cfg.get("scrape", {})
    search_cfg = tools_cfg.get("search", {})
    image_cfg = tools_cfg.get("image", {})
    vision_cfg = tools_cfg.get("vision") or {}
    ua = web_cfg.get("user_agent", "ArelisResearchBot/0.1")
    block_private = bool(agent_cfg.get("block_private_urls", True))
    research_cfg = tools_cfg.get("research") or {}

    archive: MemoryStore | None = None
    if allow_send or memory_store is not None:
        archive = memory_store or MemoryStore()
        embed_model = str(
            (config.get("memory") or {}).get("embed_model") or DEFAULT_EMBED_MODEL
        )
        embed = None
        embed_available = None
        if provider is not None:

            async def _embed(model: str, texts: list[str]) -> list[list[float]]:
                return await provider.embed(model, texts)

            async def _embed_available() -> bool:
                names = await provider.list_models()
                return any(
                    name == embed_model or name.startswith(f"{embed_model}:")
                    for name in names
                )

            embed = _embed
            embed_available = _embed_available
        registry.register(
            RecallTool(
                archive,
                embed=embed,
                embed_model=embed_model,
                embed_available=embed_available,
            )
        )
        registry.register(MemoryTool(archive))
        if tools_cfg.get("tasks", {}).get("enabled", True):
            registry.register(TasksTool(archive))
        if tools_cfg.get("goals", {}).get("enabled", True):
            registry.register(GoalsTool(archive))
        # Contact book edits need a person present for the confirm card.
        registry.register(ContactsTool())

    if tools_cfg.get("rooms", {}).get("enabled", True):
        # The store is put on the config here rather than built inside the tool
        # so the orchestrator, the agent loop and this tool all read the same
        # one. A tool with a private copy would create rooms that the command
        # entering them cannot see until something reloads the file.
        rooms_store = config.get("_rooms")
        if rooms_store is None:
            rooms_store = RoomStore()
            config["_rooms"] = rooms_store
        registry.register(RoomsTool(rooms_store))

    web_fetch_tool: WebFetchTool | None = None
    if web_cfg.get("enabled", True):
        web_fetch_tool = WebFetchTool(
            user_agent=ua,
            timeout_s=web_cfg.get("timeout_s", 30),
            block_private_urls=block_private,
        )
        registry.register(web_fetch_tool)
    scrape_tool: ScrapeTool | None = None
    if scrape_cfg.get("enabled", True):
        scrape_tool = ScrapeTool(
            user_agent=ua,
            timeout_s=web_cfg.get("timeout_s", 30),
            max_chars=scrape_cfg.get("max_chars", 120000),
            block_private_urls=block_private,
            follow_siblings=bool(scrape_cfg.get("follow_siblings", True)),
        )
        registry.register(scrape_tool)
    search_tool = None
    if search_cfg.get("enabled", True):
        search_tool = build_search_tool(
            search_cfg,
            timeout_s=float(web_cfg.get("timeout_s", 30)),
        )
        registry.register(search_tool)
    # Attended multi-source research disposer. Needs search + scrape; unattended
    # jobs skip it (allow_send=False) the same way send tools are withheld.
    if (
        allow_send
        and research_cfg.get("enabled", True)
        and search_tool is not None
        and scrape_tool is not None
    ):
        out = research_cfg.get("output_dir", "outputs/research")
        out_path = Path(out)
        if not out_path.is_absolute():
            out_path = user_data_dir() / out_path
        registry.register(
            ResearchReportTool(
                search_tool,
                scrape_tool,
                fetch=web_fetch_tool,
                max_sources=int(research_cfg.get("max_sources", 3)),
                max_chars_per_source=int(
                    research_cfg.get("max_chars_per_source", 1200)
                ),
                output_dir=out_path,
            )
        )
    # Texts leave through the user's own phone, not through the mail account,
    # so SMS is registered on its own credentials. Configuring email does not
    # configure SMS, and losing one does not take the other down with it.
    sms_cfg = tools_cfg.get("sms") or {}
    if sms_cfg.get("enabled", True):
        # Read-only: recent inbound announced while the UI was open.
        registry.register(InboundSmsTool())
        if allow_send:
            sms_account = load_sms_account()
            if sms_account is not None:
                registry.register(
                    SendSmsTool(
                        AndroidSmsProvider(
                            sms_account,
                            timeout_s=float(sms_cfg.get("timeout_s", 30)),
                        ),
                        max_body_chars=int(
                            sms_cfg.get("max_body_chars", DEFAULT_MAX_BODY_CHARS)
                        ),
                    )
                )

    email_cfg = tools_cfg.get("email", {})
    inbox_tool: InboxTool | None = None
    if email_cfg.get("enabled", True):
        # None when data/secrets.yaml is absent or blank. Both tools then stay
        # unregistered, so she says she cannot do email rather than offering a
        # tool that fails on every call.
        account = load_account()
        if account is not None:
            timeout = float(email_cfg.get("timeout_s", 30))
            mailer = Mailer(
                account,
                host=email_cfg.get("smtp_host", "smtp.gmail.com"),
                port=int(email_cfg.get("smtp_port", 587)),
                from_name=email_cfg.get("from_name", "Arelis"),
                timeout_s=timeout,
            )
            if allow_send:
                registry.register(SendEmailTool(account, mailer))
            inbox_tool = InboxTool(
                account,
                host=email_cfg.get("imap_host", "imap.gmail.com"),
                port=int(email_cfg.get("imap_port", 993)),
                timeout_s=timeout,
                max_messages=int(email_cfg.get("max_messages", 20)),
                max_body_chars=int(email_cfg.get("max_body_chars", 4000)),
            )
            registry.register(inbox_tool)
            # Scheduling exists to deliver mail, so it follows the same gate.
            # A job the runner cannot email is a job that does nothing.
            if allow_send and tools_cfg.get("schedule", {}).get("enabled", True):
                registry.register(ScheduleTool())
    # Agenda: Google/Outlook (+ ICS fallback). Writes need Allow; unattended
    # jobs do not get this tool (allow_send=False).
    #
    # tools.briefing.enabled is still read here. The briefing tool is gone, but
    # that key also stands for "keep the calendar side of the briefing working",
    # and a user who disabled the calendar while leaving briefings on still wants
    # the agenda the digest is built from.
    cal_cfg = tools_cfg.get("calendar") or {}
    if allow_send and (
        cal_cfg.get("enabled", True)
        or tools_cfg.get("briefing", {}).get("enabled", True)
    ):
        registry.register(AgendaTool(config))
    # Clipboard read needs a person for the Allow card (privacy).
    if allow_send and (tools_cfg.get("clipboard") or {}).get("enabled", True):
        registry.register(
            ClipboardTool(
                max_chars=int((tools_cfg.get("clipboard") or {}).get("max_chars", 8000)),
            )
        )
    # CPU Tesseract OCR (+ optional screen grab). Attended + confirm_vision.
    ocr_cfg = tools_cfg.get("ocr") or {}
    if allow_send and ocr_cfg.get("enabled", True):
        out = ocr_cfg.get("output_dir") or "outputs/images"
        out_path = Path(out)
        if not out_path.is_absolute():
            out_path = user_data_dir() / out_path
        registry.register(
            OcrTool(
                workspace,
                output_dir=out_path,
                max_chars=int(ocr_cfg.get("max_chars", 12_000)),
            )
        )
    registry.register(CalculatorTool())
    registry.register(CodeWorkspaceTool(workspace))
    # Read-only git; same roots as workspace. Always on when workspace is.
    registry.register(GitInfoTool(workspace))
    if tools_cfg.get("analyze", {}).get("enabled", True):
        registry.register(AnalyzeTool(workspace))
    doc_cfg = tools_cfg.get("doc_extract") or {}
    if doc_cfg.get("enabled", True):
        registry.register(
            DocExtractTool(
                workspace,
                max_chars=int(doc_cfg.get("max_chars", 20_000)),
            )
        )
    if (config.get("location") or {}).get("enabled", True):
        # Share the resolver load_config built, so a refresh triggered through
        # the tool is visible to the prompt line on the next turn.
        loc = config.get("_location") or build_location(config)
        registry.register(UserLocationTool(loc))
        # Dedicated weather tool so the chat model cannot invent broken
        # Open-Meteo query strings or scrape JS weather sites.
        registry.register(WeatherTool(loc))
    if image_cfg.get("enabled", True):
        out = image_cfg.get("output_dir", "outputs/images")
        out_path = Path(out)
        if not out_path.is_absolute():
            out_path = user_data_dir() / out_path
        launch_cwd = str(image_cfg.get("launch_cwd") or "").strip()
        if launch_cwd and not Path(launch_cwd).is_absolute():
            launch_cwd = str((user_data_dir() / launch_cwd).resolve())
        registry.register(
            ImageTool(
                comfy_url=image_cfg.get("comfy_url", "http://127.0.0.1:8188"),
                output_dir=str(out_path.resolve()),
                auto_start=bool(image_cfg.get("auto_start", False)),
                launch_command=str(image_cfg.get("launch_command") or ""),
                launch_cwd=launch_cwd,
                startup_timeout_s=float(image_cfg.get("startup_timeout_s", 120)),
            )
        )
    # Deterministic pixel work: no model, no GPU, no network. Registered even
    # for unattended jobs, because resizing a file cannot go anywhere or ask
    # anyone anything — unlike vision, which needs somebody present to Allow.
    if (tools_cfg.get("image_edit") or {}).get("enabled", True):
        registry.register(ImageEditTool(workspace))
    # Single-frame VL: attended only (Allow card). Jobs skip (allow_send=False).
    if allow_send and vision_cfg.get("enabled", True) and router is not None:
        ollama_cfg = config.get("ollama") or {}
        models_cfg = config.get("models") or {}
        vl_model = str(
            vision_cfg.get("model")
            or models_cfg.get("vision")
            or "qwen2.5vl:3b"
        ).strip()
        num_ctx = int(
            vision_cfg.get("num_ctx")
            or ollama_cfg.get("vision_num_ctx")
            or 4096
        )
        prov = provider or router.provider

        async def _vision_available() -> bool:
            names = await prov.list_models()
            return any(
                name == vl_model or name.startswith(f"{vl_model}:")
                for name in names
            )

        registry.register(
            VisionTool(
                workspace,
                router,
                model=vl_model,
                num_ctx=num_ctx,
                model_available=_vision_available,
                max_edge=int(vision_cfg.get("max_edge") or DEFAULT_MAX_EDGE),
            )
        )
        # Look-on-ask webcam stills — same Allow gate as vision; UI owns capture.
        registry.register(CameraTool(config))
    # User-browser drive: attended turns only (jobs have nobody to Allow).
    browser_cfg = tools_cfg.get("browser") or {}
    if allow_send and browser_cfg.get("enabled", True):
        from arelis.browser.session import BrowserSession

        aliases_raw = browser_cfg.get("aliases") or {}
        aliases = {
            str(k).strip().lower(): str(v).strip()
            for k, v in aliases_raw.items()
            if str(k).strip() and str(v).strip()
        }
        session = BrowserSession(
            cdp_url=str(browser_cfg.get("cdp_url") or "http://127.0.0.1:9222"),
            max_snapshot_chars=int(browser_cfg.get("max_snapshot_chars") or 6000),
            max_read_chars=int(browser_cfg.get("max_read_chars") or 3500),
        )
        registry.register(BrowserTool(session, aliases=aliases))
    return registry
