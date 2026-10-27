"""Command-bridge routes require the session token. EMP persists. The authority gate is live."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


async def test_snapshot_and_overseer_post_require_the_session_token(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Most command-bridge routes used to skip the session token.

    GET /api/snapshot and Overseer POSTs (EMP, restore, scale, file read)
    answered any loopback caller. Only /api/command checked. One gate now
    covers every non-static route. Skipping that check on snapshot or on
    the POST path is a failure of this test.

    EMP used to live only in memory. trigger_emp must persist the stop flag
    so a new hive on the same data dir refuses dispatch_task and spawns
    units as EMP_DISABLED. Skipping the file write, or the constructor
    read, is a failure of this test.

    AuthorityGate used to run only in unit tests. dispatch_task, prune,
    and warden.ban_peer now go through SwarmHive._authorize_work.
    A Tier 0 observe must run. A Tier 2 delete or prune must park and
    leave the file. Commenting out evaluate_request in dispatch_task,
    or on the prune/ban branch, is a failure of this test.

    trigger_emp trips before any lease record. A raising evaluate_request
    must still persist the stop. Startup cap housekeeping must still
    trim. Gating the halt, or routing boot trim through the operator
    prune, is a failure of this test.

    Reads stay open. A harvest GET to a public host must run with no
    sign-off. A POST off-box is a send: check_send_allowed fails closed
    and nothing is sent. Making check_send_allowed always return ok,
    mapping POST onto a proceed token, or treating an unknown send op
    as allowed, is a failure of this test.

    Arelis launch starts the Sentinel child. This test drives run_ui
    with spawn stubbed. Deleting the start call in launch.py, making
    start call restore, or logging the session token is a failure of
    this test.
    """
    import sys

    import httpx

    sentinel_root = Path(__file__).resolve().parents[1] / "sentinel"
    if str(sentinel_root) not in sys.path:
        sys.path.insert(0, str(sentinel_root))

    from sentinel.bridge.protocol import TOKEN_HEADER
    from sentinel.bridge.server import SentinelBridgeServer

    class _Hive:
        async def start_background_loops(self, *, hz: int = 60) -> None:
            return None

        async def stop_background_loops(self) -> None:
            return None

        def world_snapshot(self) -> dict[str, Any]:
            return {"units": []}

        async def set_theme(self, theme_id: str) -> dict[str, Any]:
            return {"id": theme_id}

    token = "testtoken"
    server = SentinelBridgeServer(
        _Hive(),
        host="127.0.0.1",
        preferred_port=0,
        token=token,
    )
    port = await server.start()
    try:
        url = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient() as http:
            snap_bare = await http.get(f"{url}/api/snapshot")
            assert snap_bare.status_code == 401

            post_bare = await http.post(
                f"{url}/api/overseer/theme",
                json={"theme": "night"},
            )
            assert post_bare.status_code == 401

            headers = {TOKEN_HEADER: token}
            snap_ok = await http.get(f"{url}/api/snapshot", headers=headers)
            assert snap_ok.status_code == 200
            assert "units" in snap_ok.json()

            post_ok = await http.post(
                f"{url}/api/overseer/theme",
                json={"theme": "night"},
                headers=headers,
            )
            assert post_ok.status_code == 200
    finally:
        await server.stop()

    from sentinel.castes.warden import WardenCaste
    from sentinel.core.fsm import SentinelState
    from sentinel.core.hive import SwarmHive
    from sentinel.paths import harvest_dir, quarantine_dir, set_runtime_root

    hive_cfg = {
        "swarm": {
            "initial_pools": {
                "harvester": 1,
                "warden": 1,
                "sanitizer": 1,
                "tripwire": 1,
            },
            "auto_scale": False,
            "max_total_units": 8,
            "default_tier": "mk1",
        },
        "tripwire": {"watched_roots": []},
        "warden": {"watched_ports": []},
    }
    set_runtime_root(tmp_path)
    try:
        hive = SwarmHive(hive_cfg)

        def _raise_gate(*_a: object, **_k: object) -> tuple[bool, object]:
            raise RuntimeError("gate down")

        hive.authority.evaluate_request = _raise_gate  # type: ignore[method-assign]
        await hive.trigger_emp(reason="persist across restart")
        assert hive.emp.is_tripped is True
        restarted = SwarmHive(hive_cfg)
        blocked = await restarted.dispatch_task("warden", {"action": "patrol_scan"})
        assert blocked["ok"] is False
        assert all(u.state == SentinelState.EMP_DISABLED for u in restarted.units.values())
    finally:
        set_runtime_root(None)

    set_runtime_root(tmp_path / "gate")
    try:
        h_dir = harvest_dir()
        q_dir = quarantine_dir()
        for i in range(5):
            (h_dir / f"2026-10-16-test-harvest-{i:02d}.md").write_text(f"# H {i}\n", encoding="utf-8")
            (q_dir / f"quarantine-179220000{i}-abcd1234.json").write_text("{}\n", encoding="utf-8")
        gate_cfg = dict(hive_cfg)
        gate_cfg["retention"] = {"max_harvest_dossiers": 2, "max_quarantine_files": 2}
        gated = SwarmHive(gate_cfg)
        assert len(list(h_dir.glob("*.md"))) == 2
        assert len(list(q_dir.glob("quarantine-*.json"))) == 2

        observe = await gated.dispatch_task(
            "warden",
            {"action": "patrol_scan", "animate": False},
        )
        assert observe["ok"] is True

        qfile = quarantine_dir() / "quarantine-1792200001-deadbeef.json"
        qfile.parent.mkdir(parents=True, exist_ok=True)
        qfile.write_text('{"keep": true}\n', encoding="utf-8")

        parked = await gated.dispatch_task(
            "sanitizer",
            {"action": "DELETE_QUARANTINE_FILE", "path": str(qfile), "animate": False},
        )
        assert parked["ok"] is False
        assert parked.get("parked") is True
        assert qfile.is_file()

        pruned = gated.prune_runtime_storage(max_quarantines=0)
        assert pruned["ok"] is False
        assert pruned.get("parked") is True
        assert qfile.is_file()

        wrd = gated.registry.get("warden")
        assert isinstance(wrd, WardenCaste)
        ban = wrd.ban_peer("198.51.100.42", reason="control-test ban")
        assert ban.get("parked") is True
        banned, _entry = wrd.is_banned("198.51.100.42")
        assert banned is False

        from sentinel.castes.harvester import HarvesterCaste
        from sentinel.safety import network as netmod

        hrv = gated.registry.get("harvester")
        assert isinstance(hrv, HarvesterCaste)
        sent: list[tuple[str, str]] = []
        html = (
            "<html><head><title>Public harvest article</title></head>"
            "<body><article>"
            "<p>Public host harvest text used to prove a GET read proceeds without operator sign-off.</p>"
            "<p>Second paragraph so the extractor keeps more than one line of article body.</p>"
            "</article></body></html>"
        )

        def _handler(request: httpx.Request) -> httpx.Response:
            sent.append((request.method, str(request.url)))
            return httpx.Response(
                200,
                text=html,
                headers={"content-type": "text/html"},
                request=request,
            )

        orig_resolve = netmod._resolve_all_ips
        netmod._resolve_all_ips = lambda host, port: ["93.184.216.34"]
        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        hrv._external_client = client
        try:
            harvested = await gated.dispatch_task(
                "harvester",
                {
                    "action": "url",
                    "url": "https://example.com/harvest",
                    "method": "GET",
                    "animate": False,
                },
            )
            assert harvested["ok"] is True
            assert harvested.get("parked") is not True
            assert sent and all(m == "GET" for m, _u in sent)

            sent.clear()
            posted = await gated.dispatch_task(
                "harvester",
                {
                    "action": "url",
                    "url": "https://example.com/submit",
                    "method": "POST",
                    "animate": False,
                },
            )
            assert posted["ok"] is False
            assert posted.get("parked") is True
            assert sent == []

            for extra in ({"method": "GET"}, {}):
                leaked = await gated.dispatch_task(
                    "harvester",
                    {
                        "action": "url",
                        "url": "https://example.com/harvest?q=secret",
                        "animate": False,
                        **extra,
                    },
                )
                assert leaked.get("parked") is True
                assert sent == []
        finally:
            await client.aclose()
            hrv._external_client = None
            netmod._resolve_all_ips = orig_resolve
    finally:
        set_runtime_root(None)

    import logging
    import os
    import time
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from sentinel.bridge import client as client_mod
    from sentinel.bridge.protocol import overseer_open_url
    from sentinel.core import emp as emp_mod
    from sentinel.core.hive import SwarmHive

    import arelis.sentinel_control as ctl
    from arelis.sentinel_control import stop

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("ARELIS_ALLOW_OFFSCREEN", "1")
    from PySide6.QtWidgets import QApplication, QWidget

    from arelis.ui import launch as launch_mod

    hud = overseer_open_url("127.0.0.1", 8790, "controltok")
    assert hud.endswith("#token=controltok")

    data_root = tmp_path / "arelis-data"
    data_root.mkdir()
    emp = data_root / "sentinel" / "data" / "emp_flag"
    emp.parent.mkdir(parents=True)
    emp.write_text("1\n", encoding="utf-8")
    child_token = "c" * 64
    spawned: list[dict[str, Any]] = []
    restore_hits: list[str] = []

    def _spawn_child(argv: list[str], **kwargs: Any) -> MagicMock:
        spawned.append({"argv": list(argv), "env": dict(kwargs.get("env") or {})})
        env = kwargs.get("env") or {}
        root = Path(str(env.get("SENTINEL_RUNTIME_ROOT") or ""))
        token_file = root / "data" / "session_token"
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(child_token, encoding="utf-8")
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.pid = 0
        return proc

    def _restore_trap(*_a: object, **_k: object) -> dict[str, object]:
        restore_hits.append("restore")
        return {"ok": True, "tripped": False}

    class _Router:
        provider = None

        def arm_warmup(self) -> None:
            return None

        def mark_warmup_done(self) -> None:
            return None

        async def close(self) -> None:
            return None

    fake_seat = SimpleNamespace(
        router=_Router(),
        store=None,
        tools={},
        orchestrator=SimpleNamespace(),
    )

    class QuietWindow(QWidget):
        def __init__(self, *_a: object, **_k: object) -> None:
            super().__init__()
            self._force_quit = True
            self.orchestrator = fake_seat.orchestrator
            self.inbound_runtime = None
            self.ipc_client = None
            self.ipc_server = None
            self._pending_store = SimpleNamespace(list=lambda: [])
            self._orphan_ingest_stop = None
            self.sms_ingest = None
            self.sms_watcher = None
            self.sms_auto_reply = None
            self.config = {}

        def setup_tray(self, app: object) -> None:
            del app

        def queue_pending_confirms(self, parked: object) -> None:
            del parked

    def _wait_exec(_self: object = None) -> int:
        deadline = time.monotonic() + 2.0
        while not held_token and time.monotonic() < deadline:
            time.sleep(0.01)
        return 0

    prior = os.environ.get("ARELIS_DATA_DIR")
    os.environ["ARELIS_DATA_DIR"] = str(data_root)
    real_spawn = ctl._spawn
    real_clear = emp_mod.clear_emp_flag
    real_restore_swarm = emp_mod.EMPController.restore_swarm
    real_restore_hive = SwarmHive.restore_from_emp
    real_restore_client = client_mod.SentinelClient.emp_restore
    try:
        ctl._spawn = _spawn_child  # type: ignore[method-assign]
        ctl._stopped = False
        ctl._process = None
        ctl._token = None
        ctl.restore = _restore_trap  # type: ignore[attr-defined]
        held_token: list[str | None] = []
        orig_start = ctl.start

        def _hold_start() -> None:
            orig_start()
            held_token.append(ctl._token)

        monkeypatch.setattr(ctl, "start", _hold_start)
        emp_mod.clear_emp_flag = _restore_trap  # type: ignore[assignment]
        emp_mod.EMPController.restore_swarm = _restore_trap  # type: ignore[method-assign]
        SwarmHive.restore_from_emp = _restore_trap  # type: ignore[method-assign]
        client_mod.SentinelClient.emp_restore = _restore_trap  # type: ignore[method-assign]
        monkeypatch.setattr(launch_mod, "apply_first_run_glass", lambda *_a, **_k: {})
        monkeypatch.setattr("arelis.core.seat.build_seat", lambda *_a, **_k: fake_seat)
        monkeypatch.setattr(launch_mod, "VoiceService", lambda *_a, **_k: SimpleNamespace(stt=None))
        monkeypatch.setattr(
            launch_mod,
            "MemoryIndexer",
            lambda *_a, **_k: SimpleNamespace(join_writes=lambda timeout_s=0: None),
        )
        monkeypatch.setattr("arelis.ui.app.ArelisWindow", QuietWindow)
        monkeypatch.setattr(QApplication, "exec", _wait_exec)
        monkeypatch.setattr("arelis.i18n.apply_language", lambda *_a, **_k: None)
        monkeypatch.setattr(launch_mod, "_present_at_startup", lambda window: None)
        monkeypatch.setattr("arelis.ui.update_prompt.schedule_update_check", lambda *_a, **_k: None)
        monkeypatch.setattr(launch_mod, "_start_activation_listener", lambda *_a, **_k: None)
        monkeypatch.setattr(
            "arelis.presence.glass_inbound.install_owned_inbound", lambda *_a, **_k: None
        )
        monkeypatch.setattr("arelis.presence.lock.external_core_available", lambda _c: False)
        monkeypatch.setattr(
            launch_mod, "ConfirmPersister", lambda *_a, **_k: SimpleNamespace(start=lambda: None)
        )
        monkeypatch.setattr("arelis.tools.comfy_lifecycle.park_comfy", lambda: None)
        with caplog.at_level(logging.DEBUG, logger="arelis.sentinel_control"):
            assert launch_mod.run_ui({}) == 0
        assert spawned, "run_ui must start the child"
        argv0 = spawned[0]["argv"]
        assert "--headless" in argv0
        assert "--restore" not in argv0
        assert spawned[0]["env"].get("SENTINEL_RUNTIME_ROOT") == str(data_root / "sentinel")
        assert held_token == [child_token]
        assert emp.read_text(encoding="utf-8").strip() == "1"
        assert restore_hits == []
        assert child_token not in caplog.text
        stop()
    finally:
        ctl._spawn = real_spawn
        if hasattr(ctl, "restore"):
            delattr(ctl, "restore")
        emp_mod.clear_emp_flag = real_clear
        emp_mod.EMPController.restore_swarm = real_restore_swarm
        SwarmHive.restore_from_emp = real_restore_hive
        client_mod.SentinelClient.emp_restore = real_restore_client
        stop()
        if prior is None:
            os.environ.pop("ARELIS_DATA_DIR", None)
        else:
            os.environ["ARELIS_DATA_DIR"] = prior
