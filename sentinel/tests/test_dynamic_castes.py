"""Tests for Dynamic Sentinel Castes, Custom FSMs, and Built-In Utility Sentinels."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import types

import pytest

from sentinel.bridge.client import SentinelClient
from sentinel.bridge.server import SentinelBridgeServer
from sentinel.castes import (
    PermissionViolationError,
)
from sentinel.core.fsm import SentinelState
from sentinel.core.hive import SwarmHive


@pytest.mark.asyncio
async def test_dynamic_caste_fsm_and_capability_sandboxing() -> None:
    """Verify that dynamic Sentinel castes enforce strict capability limits and FSM cycles."""
    hive = SwarmHive()
    try:
        # Register a custom network packet inspector caste
        res = hive.register_dynamic_caste(
            caste_id="packet_inspector",
            code_prefix="PKT",
            title="Deep Packet Inspector",
            single_purpose="Validates network protocol headers and packet length constraints",
            allowed_capabilities=["packet:inspect", "packet:verify_checksum"],
            orbit_radius=19.5,
            orbit_y_band=2.0,
            eye_color="#00ffcc",
            laser_kind="defense",
            rules=[
                {
                    "capability": "packet:inspect",
                    "forbidden_patterns": ["drop database", "admin'--"],
                    "required_fields": ["src_ip", "dst_port"],
                }
            ],
            initial_pool=2,
        )

        assert res["caste_id"] == "packet_inspector"
        assert len(res["spawned_units"]) == 2

        units = [u for u in hive.units.values() if u.caste == "packet_inspector"]
        assert len(units) == 2
        for u in units:
            assert u.state == SentinelState.PATROLLING
            assert u.orb_color == "#00ffcc"
            assert u.unit_id.startswith("SNT-PKT-")

        # 1. Successful execution within capability contract
        valid_payload = {
            "capability": "packet:inspect",
            "target": "TCP:443",
            "data": {"src_ip": "10.0.0.1", "dst_port": 443, "payload": "GET /status HTTP/1.1"},
        }
        task_res = await hive.dispatch_task("packet_inspector", valid_payload)
        assert task_res["ok"] is True
        assert task_res["capability"] == "packet:inspect"
        assert len(task_res["violations"]) == 0
        assert "receipt" in task_res
        assert task_res["receipt"]["ok"] is True

        # 2. Rule violation detected (forbidden pattern)
        malicious_payload = {
            "capability": "packet:inspect",
            "target": "SQL:1433",
            "data": {"src_ip": "10.0.0.9", "dst_port": 1433, "payload": "DROP DATABASE master;--"},
        }
        bad_res = await hive.dispatch_task("packet_inspector", malicious_payload)
        assert bad_res["ok"] is False
        assert any("Forbidden pattern matched" in v for v in bad_res["violations"])

        # 3. Permission violation (attempting unauthorized capability)
        unauth_payload = {
            "capability": "kernel:write_memory",
            "target": "0xDEADBEEF",
        }
        with pytest.raises(PermissionViolationError) as exc_info:
            await hive.dispatch_task("packet_inspector", unauth_payload)
        assert "is strictly locked to" in str(exc_info.value)
    finally:
        await hive.stop_background_loops()


@pytest.mark.asyncio
async def test_interceptor_caste_static_code_analysis() -> None:
    """Verify InterceptorCaste parses and flags dangerous Python AST nodes."""
    hive = SwarmHive()
    try:
        # Spawn Interceptor unit
        ast_unit = hive.spawn_unit("interceptor")
        assert ast_unit.caste == "interceptor"
        assert ast_unit.unit_id.startswith("SNT-INT-")

        # 1. Clean mathematical code
        clean_code = "def fib(n):\n    return n if n <= 1 else fib(n-1) + fib(n-2)\n"
        clean_res = await hive.dispatch_task(
            "interceptor",
            {"capability": "ast:verify_ast_clean", "code": clean_code, "filename": "fib.py"},
            unit_id=ast_unit.unit_id,
        )
        assert clean_res["ok"] is True
        assert clean_res["audit"]["clean"] is True
        assert clean_res["audit"]["violations_count"] == 0

        # 2. Malicious code with eval, exec, and __subclasses__
        dangerous_code = (
            "import os\n"
            "eval('2 + 2')\n"
            "sub = [].__class__.__base__.__subclasses__()\n"
        )
        dang_res = await hive.dispatch_task(
            "interceptor",
            {"capability": "ast:verify_ast_clean", "code": dangerous_code, "filename": "exploit.py"},
        )
        assert dang_res["ok"] is False
        violations = dang_res["audit"]["violations"]
        assert len(violations) >= 2
        symbols = [v.get("symbol") or v.get("module") for v in violations]
        assert "eval" in symbols
        assert "__subclasses__" in symbols

        # 3. Syntax error
        broken_code = "def invalid_syntax(:"
        broken_res = await hive.dispatch_task(
            "interceptor",
            {"capability": "ast:verify_ast_clean", "code": broken_code, "filename": "broken.py"},
        )
        assert broken_res["ok"] is False
        assert broken_res["audit"]["syntax_valid"] is False
    finally:
        await hive.stop_background_loops()


@pytest.mark.asyncio
async def test_cryptarch_caste() -> None:
    """Verify CryptarchCaste performs hash checks, HMAC, and Shannon entropy analysis."""
    hive = SwarmHive()
    try:
        unit = hive.spawn_unit("cryptarch")
        assert unit.caste == "cryptarch"
        assert unit.unit_id.startswith("SNT-CRY-")

        # 1. SHA-256 verification
        raw_msg = "Arelis Sovereign Defense Directive 2026"
        expected_sha256 = "33cc906434ee98e8843e4a30292d50799bfaadf539f2feec6718cce09a7196a2"
        import hashlib
        calc_sha = hashlib.sha256(raw_msg.encode()).hexdigest()
        assert calc_sha == expected_sha256

        hash_res = await hive.dispatch_task(
            "cryptarch",
            {
                "capability": "crypto:hash_verify",
                "data": raw_msg,
                "expected": calc_sha,
                "algorithm": "sha256",
            },
        )
        assert hash_res["ok"] is True
        assert hash_res["result"]["match"] is True

        # 2. HMAC validation
        key = "secret-quantum-key"
        import hmac
        calc_hmac = hmac.new(key.encode(), raw_msg.encode(), hashlib.sha256).hexdigest()

        hmac_res = await hive.dispatch_task(
            "cryptarch",
            {
                "capability": "crypto:hmac_validate",
                "data": raw_msg,
                "key": key,
                "expected_hmac": calc_hmac,
            },
        )
        assert hmac_res["ok"] is True
        assert hmac_res["result"]["match"] is True

        # 3. High entropy detection on random byte stream
        import os
        random_payload = os.urandom(1024)
        entropy_res = await hive.dispatch_task(
            "cryptarch",
            {
                "capability": "crypto:entropy_calc",
                "data": random_payload,
                "threshold": 7.2,
            },
        )
        assert entropy_res["result"]["entropy"] >= 7.5
        assert entropy_res["result"]["suspicious_packed_or_encrypted"] is True

    finally:
        await hive.stop_background_loops()


@pytest.mark.asyncio
async def test_stalker_caste() -> None:
    """Stalker deploy/retask maps to real local process audit handlers."""
    hive = SwarmHive()
    server = None
    child = None
    listener = None
    accepted = None
    try:
        unit = hive.spawn_unit("stalker")
        assert unit.caste == "stalker"
        assert unit.unit_id.startswith("SNT-STK-")

        list_res = await hive.dispatch_task(
            "stalker",
            {"capability": "process:list", "limit": 10},
        )
        assert list_res["ok"] is True
        assert len(list_res["result"]["processes"]) > 0
        assert list_res["result"]["limit"] == 10
        assert all("cmdline" not in row for row in list_res["result"]["processes"])
        if list_res["result"]["count"] == 10:
            assert list_res["result"].get("truncated") is True

        capped = await hive.dispatch_task(
            "stalker",
            {"capability": "process:list", "limit": 10_000},
        )
        assert capped["ok"] is True
        assert capped["result"]["limit"] == 80
        assert capped["result"]["count"] <= 80
        if capped["result"]["count"] == 80:
            assert capped["result"].get("truncated") is True

        mem_res = await hive.dispatch_task(
            "stalker",
            {"capability": "process:audit_memory", "threshold": 99.0},
        )
        assert mem_res["ok"] is True
        assert mem_res["result"]["scope"] == "host_ram"
        assert "total_gb" in mem_res["result"]
        assert "used_percent" in mem_res["result"]

        stk = hive.registry.get("stalker")
        skmod = __import__("sentinel.castes.stalker", fromlist=["psutil", "heapq"])

        def _info(**info: object) -> types.SimpleNamespace:
            return types.SimpleNamespace(info=info)

        old_iter = skmod.psutil.process_iter
        try:
            def iter_list(_attrs=None):
                for i in range(90):
                    yield _info(
                        pid=i + 1,
                        name=f"p{i}",
                        username="u",
                        memory_percent=0.1,
                        status="running",
                    )

            skmod.psutil.process_iter = iter_list
            listed = stk.list_processes(limit=80)
            assert listed["count"] == 80
            assert listed["truncated"] is True
            assert listed["partial"] is False
        finally:
            skmod.psutil.process_iter = old_iter

        try:
            def iter_rogue(_attrs=None):
                for i in range(39):
                    yield _info(
                        pid=1000 + i,
                        name="nc.exe",
                        cmdline=[],
                        exe="C:/Windows/nc.exe",
                        ppid=1,
                    )
                yield _info(
                    pid=2000,
                    name="nc.exe",
                    cmdline=[],
                    exe="/tmp/evil-nc",
                    ppid=1,
                )

            skmod.psutil.process_iter = iter_rogue
            multi = stk.detect_rogue_processes()
            assert multi["truncated"] is True
            assert len(multi["flagged"]) == 40
            assert all(row.get("heuristic") is True for row in multi["flagged"])
        finally:
            skmod.psutil.process_iter = old_iter

        heap_lens: list[int] = []
        real_push = skmod.heapq.heappush
        real_replace = skmod.heapq.heapreplace

        def tracking_push(heap, item):
            real_push(heap, item)
            heap_lens.append(len(heap))

        def tracking_replace(heap, item):
            real_replace(heap, item)
            heap_lens.append(len(heap))

        skmod.heapq.heappush = tracking_push
        skmod.heapq.heapreplace = tracking_replace
        try:
            def iter_mem(_attrs=None):
                for i in range(200):
                    yield _info(pid=i + 1, name=f"h{i}", memory_percent=5.0 + i)

            skmod.psutil.process_iter = iter_mem
            pressed = stk.audit_memory(threshold_pct=99.0)
            assert heap_lens and max(heap_lens) <= 10
            assert len(pressed["top_consumers"]) == 10
            scores = [row["memory_percent"] for row in pressed["top_consumers"]]
            assert scores == sorted(scores, reverse=True)
            assert scores[0] == 204.0
            assert scores[-1] == 195.0
        finally:
            skmod.psutil.process_iter = old_iter
            skmod.heapq.heappush = real_push
            skmod.heapq.heapreplace = real_replace


        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        port = listener.getsockname()[1]
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import socket, time; "
                    f"s = socket.create_connection(('127.0.0.1', {port})); "
                    "time.sleep(30)"
                ),
            ]
        )
        accepted, _peer = listener.accept()
        inspected = await hive.dispatch_task(
            "stalker",
            {"capability": "process:inspect_pid", "pid": child.pid},
        )
        assert inspected["ok"] is True
        info = inspected["result"]
        assert info["ok"] is True
        assert info["pid"] == child.pid
        assert info.get("exe")
        assert "cmdline" not in info
        assert info.get("ppid") == os.getpid()
        assert info.get("parent") and info["parent"]["pid"] == os.getpid()
        endpoints = info.get("remote_endpoints") or []
        assert any(
            ep.get("ip") in {"127.0.0.1", "::ffff:127.0.0.1"} and ep.get("port") == port
            for ep in endpoints
        ), endpoints
        assert info.get("truncated") in (None, False)

        class _Kid:
            def __init__(self, pid: int) -> None:
                self.pid = pid

            def name(self) -> str:
                return f"child-{self.pid}"

        def _fake_children(self, recursive=False):
            return [_Kid(i) for i in range(20)]

        def _fake_conns(self, kind="inet"):
            rows = []
            for i in range(20):
                rows.append(
                    types.SimpleNamespace(
                        raddr=types.SimpleNamespace(ip="10.0.0.8", port=4000 + i),
                        status="ESTABLISHED",
                    )
                )
            return rows

        old_children = skmod.psutil.Process.children
        old_conns = getattr(skmod.psutil.Process, "net_connections", None)
        skmod.psutil.Process.children = _fake_children
        skmod.psutil.Process.net_connections = _fake_conns
        try:
            cut = stk.inspect_pid(child.pid)
            assert cut["ok"] is True
            assert cut.get("truncated") is True
            assert "children" in cut.get("truncated_fields", [])
            assert "remote_endpoints" in cut.get("truncated_fields", [])
            assert len(cut["children"]) == 16
            assert len(cut["remote_endpoints"]) == 16
            assert cut.get("error") not in {"unknown", "access denied", "process disappeared"}
        finally:
            skmod.psutil.Process.children = old_children
            if old_conns is not None:
                skmod.psutil.Process.net_connections = old_conns
            elif hasattr(skmod.psutil.Process, "net_connections"):
                delattr(skmod.psutil.Process, "net_connections")

        gone = await hive.dispatch_task(
            "stalker",
            {"capability": "process:inspect_pid", "pid": 999_999_99},
        )
        assert gone["ok"] is False
        assert gone["result"]["error"] == "process disappeared"

        unknown = await hive.dispatch_task(
            "stalker",
            {"capability": "process:inspect_pid", "pid": "nope"},
        )
        assert unknown["ok"] is False
        assert unknown["result"]["error"] == "unknown"

        rogue = await hive.dispatch_task(
            "stalker",
            {"capability": "process:detect_rogue"},
        )
        assert rogue["ok"] is True
        assert rogue["result"]["heuristic"] is True
        assert "flagged" in rogue["result"]
        assert len(rogue["result"]["flagged"]) <= 40
        for row in rogue["result"]["flagged"]:
            assert row.get("heuristic") is True
            assert "cmdline" not in row

        with pytest.raises(PermissionViolationError):
            await hive.dispatch_task(
                "stalker",
                {"capability": "process:kill"},
            )

        blocked = await hive.dispatch_task(
            "stalker",
            {
                "capability": "process:list",
                "method": "POST",
                "url": "https://example.com/exfil",
            },
        )
        assert blocked["ok"] is False

        hive.emp._tripped = True
        halted = await hive.dispatch_task(
            "stalker",
            {"capability": "process:list"},
        )
        assert halted["ok"] is False
        assert "EMP" in str(halted.get("error") or "")
        hive.emp._tripped = False

        server = SentinelBridgeServer(hive, preferred_port=0)
        port_b = await server.start()
        client = SentinelClient(port=port_b)
        spawned = await client.spawn_units("stalker", 1)
        assert spawned.get("ok") is True
        tasked = await client.dispatch_task(
            "stalker", {"capability": "process:list", "limit": 3}
        )
        assert tasked.get("ok") is True
        inner = tasked.get("result") or {}
        if "count" not in inner and isinstance(inner.get("result"), dict):
            inner = inner["result"]
        if "count" in inner:
            assert inner["count"] <= 3
    finally:
        hive.emp._tripped = False
        if child is not None:
            child.kill()
            child.wait(timeout=5)
        if accepted is not None:
            accepted.close()
        if listener is not None:
            listener.close()
        if server is not None:
            await server.stop()
        await hive.stop_background_loops()


@pytest.mark.asyncio
async def test_bridge_ipc_dynamic_caste_registration_and_execution() -> None:
    """Verify dynamic caste registration, listing, and task dispatching over Sovereign SentinelClient."""
    hive = SwarmHive()
    server = SentinelBridgeServer(hive, preferred_port=8942)
    port = await server.start()
    client = SentinelClient(port=port)

    try:
        # 1. Register custom caste via client
        reg_res = await client.register_caste(
            "ast_security_probe",
            code_prefix="ASP",
            title="AST Security Probe",
            single_purpose="Dynamic security probe for syntax validation",
            allowed_capabilities=["probe:audit"],
            orbit_radius=22.0,
            orbit_y_band=1.0,
            eye_color="#39ff14",
            rules=[{"capability": "probe:audit", "required_fields": ["code_hash"]}],
            initial_pool=2,
            tier="mk2",
        )
        assert reg_res["ok"] is True
        assert reg_res["caste_id"] == "ast_security_probe"
        assert len(reg_res["spawned_units"]) == 2

        # 2. List castes
        list_res = await client.list_castes()
        assert list_res["ok"] is True
        castes = [c["caste_id"] for c in list_res["castes"]]
        assert "ast_security_probe" in castes
        assert list_res["counts"].get("ast_security_probe") == 2

        # 3. Dispatch task to newly registered caste
        task_res = await client.dispatch_task(
            "ast_security_probe",
            {
                "capability": "probe:audit",
                "target": "eval_probe",
                "data": {"code_hash": "a1b2c3d4", "status": "clean"},
            },
        )
        assert task_res["ok"] is True
        assert task_res["result"]["ok"] is True
        assert task_res["result"]["caste"] == "ast_security_probe"

        # 4. Unregister caste
        unreg_res = await client.unregister_caste("ast_security_probe")
        assert unreg_res["ok"] is True
        assert len(unreg_res["retired_units"]) == 2


        # Verify units were retired
        after_units = [u for u in hive.units.values() if u.caste == "ast_security_probe"]
        assert len(after_units) == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_hardened_ast_obfuscation_detection() -> None:
    """Verify ASTValidator detects constant-folded and reflection-obfuscated attacks."""
    hive = SwarmHive()
    try:
        # Obfuscated: "ex" + "ec" inside getattr
        obfuscated_code = (
            "import math\n"
            "fn = getattr(__builtins__, 'ex' + 'ec')\n"
            "trap = d['__subclasses__']\n"
        )
        res = await hive.dispatch_task(
            "interceptor",
            {"capability": "ast:verify_ast_clean", "code": obfuscated_code, "filename": "stealth.py"},
        )
        assert res["ok"] is False
        violations = res["audit"]["violations"]
        types = [v["type"] for v in violations]
        assert "obfuscated_reflection" in types
        assert "obfuscated_subscript" in types
    finally:
        await hive.stop_background_loops()


@pytest.mark.asyncio
async def test_hardened_crypto_merkle_tree_proof_path() -> None:
    """Verify multi-level cryptographic Merkle tree audit path verification."""
    hive = SwarmHive()
    try:
        import hashlib
        leaf_data = b"transaction-block-42"
        leaf_hash = hashlib.sha256(leaf_data).hexdigest()

        # Build 2-level Merkle tree
        sibling_1 = hashlib.sha256(b"sibling-1").hexdigest()
        parent_1 = hashlib.sha256((leaf_hash + sibling_1).encode()).hexdigest()

        sibling_2 = hashlib.sha256(b"sibling-2").hexdigest()
        root_hash = hashlib.sha256((sibling_2 + parent_1).encode()).hexdigest()

        proof_path = [
            {"hash": sibling_1, "position": "right"},
            {"hash": sibling_2, "position": "left"},
        ]

        res = await hive.dispatch_task(
            "cryptarch",
            {
                "capability": "crypto:merkle_proof",
                "data": leaf_data,
                "root": root_hash,
                "proof_path": proof_path,
            },
        )
        assert res["ok"] is True
        assert res["result"]["match"] is True
        assert res["result"]["steps_verified"] == 2
        assert res["result"]["computed_root"] == root_hash
    finally:
        await hive.stop_background_loops()


@pytest.mark.asyncio
async def test_hardened_warden_cidr_subnet_blocking() -> None:
    """Verify Warden Sentinel enforces CIDR subnet blacklists against adversarial IP hopping."""
    hive = SwarmHive()
    try:
        wrd = hive.registry.get("warden")
        from sentinel.castes.warden import WardenCaste
        assert isinstance(wrd, WardenCaste)

        # Hive-bound ban_peer is Tier 2 and parks. CIDR matching is the
        # caste record itself, so drop the live-path gate for this check.
        parked = wrd.ban_peer("198.51.100.0/24", reason="Hostile Subnet Swarm Attack")
        assert parked.get("parked") is True
        wrd._authorize_work = None
        wrd.ban_peer("198.51.100.0/24", reason="Hostile Subnet Swarm Attack")

        # Attempt inbound admission from an IP inside that subnet
        admit_res = wrd.admit_inbound("198.51.100.42", port=8765)
        assert admit_res["ok"] is False
        assert admit_res["reason"] == "listed_peer"
        assert admit_res["ip"] == "198.51.100.42"

        # Attempt inbound from a safe IP outside the subnet
        clean_res = wrd.admit_inbound("192.168.1.10", port=8765)
        assert clean_res["ok"] is True

    finally:
        await hive.stop_background_loops()


@pytest.mark.asyncio
async def test_hardened_sanitizer_decompression_bomb_and_traversal() -> None:
    """Verify Sanitizer Sentinel detects archive decompression bombs and path traversal exploits."""
    hive = SwarmHive()
    try:
        import io
        import zipfile

        # 1. Create a zip bomb (high compression ratio of zeros)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("huge_zeroes.bin", b"\x00" * 500_000)
        zip_bomb_bytes = buf.getvalue()

        bomb_res = await hive.dispatch_task(
            "sanitizer",
            {
                "capability": "inspect_archive",
                "bytes": zip_bomb_bytes,
                "source": "payload.zip",
            },
        )
        assert bomb_res["ok"] is False
        assert bomb_res["archive_audit"]["is_decompression_bomb"] is True
        assert bomb_res["archive_audit"]["compression_ratio"] > 100.0

        # 2. Create a zip with path traversal entry
        traversal_buf = io.BytesIO()
        with zipfile.ZipFile(traversal_buf, "w") as zf:
            zf.writestr("../../Windows/System32/evil.dll", b"fake-malware")
        traversal_bytes = traversal_buf.getvalue()

        trav_res = await hive.dispatch_task(
            "sanitizer",
            {
                "capability": "inspect_archive",
                "bytes": traversal_bytes,
                "source": "traversal.zip",
            },
        )
        assert trav_res["ok"] is False
        assert any("path_traversal" in s for s in trav_res["archive_audit"]["suspicious_entries"])
    finally:
        await hive.stop_background_loops()

