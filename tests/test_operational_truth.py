"""Isolated regressions: load job coordinator only; never instantiate host Sentinel.

Run directly with Python -B. No pytest conftest, host scans, network, or source imports.
"""

import ast
import asyncio
import importlib.util
import socket
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "sentinel").is_dir():
    ROOT = Path(r"C:\Users\origi\Documents\Arelis_Sentinel")
spec = importlib.util.spec_from_file_location(
    "isolated_live_director", ROOT / "sentinel/core/simulator.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def load_method(path, cls, method, globals_=None):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    fn = next(n for n in node.body if getattr(n, "name", "") == method)
    isolated = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            fn,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated)
    namespace = dict(globals_ or {})
    exec(compile(isolated, str(path), "exec"), namespace)  # noqa: S102 - local source under test
    return namespace[method]


class LiveMissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Windows creates its internal asyncio socketpair before setUp; block
        # all subsequent connections during the test itself.
        for target, name in [
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (socket.socket, "connect"),
        ]:
            guard = patch.object(target, name, side_effect=AssertionError("Network prohibited"))
            guard.start()
            self.addCleanup(guard.stop)
        self.hive = types.SimpleNamespace(
            emp=types.SimpleNamespace(is_tripped=False, track_task=lambda task: task),
            dispatch_harvest_swarm=AsyncMock(
                return_value={"succeeded": 2, "total_targets": 2, "failed": 0}
            ),
            dispatch_task=AsyncMock(),
        )
        self.director = module.SimulationDirector(self.hive)

    async def launch(self, mode="multi", query="stellar nucleosynthesis"):
        result = await self.director.run_live_mission(mode, query)
        self.assertTrue(result["ok"])
        await self.director._active_task

    async def test_removed_scenarios_never_dispatch_or_emit(self):
        for name in [
            "zion_siege",
            "science_harvest",
            "injection_attack",
            "cyber_intrusion",
            "tripwire_breach",
            "binary_polyglot_trap",
            "unknown",
            "",
        ]:
            self.assertFalse((await self.director.run_scenario(name))["ok"])
        self.hive.dispatch_task.assert_not_called()
        self.hive.dispatch_harvest_swarm.assert_not_called()
        self.assertEqual(self.director.fx_events, [])

    async def test_full_topic_without_unrelated_planets(self):
        await self.launch()
        targets = self.hive.dispatch_harvest_swarm.call_args.args[1]
        self.assertEqual(
            targets,
            [
                {"action": "arxiv", "query": "stellar nucleosynthesis", "max_results": 4},
                {"action": "wikipedia", "query": "stellar nucleosynthesis"},
            ],
        )
        self.assertTrue(self.director.last_result["ok"])

    async def test_explicit_horizons_target(self):
        await self.launch("horizons", "Europa")
        self.assertEqual(
            self.hive.dispatch_harvest_swarm.call_args.args[1],
            [{"action": "horizons", "target": "Europa"}],
        )

    async def test_partial_failure_is_not_success(self):
        self.hive.dispatch_harvest_swarm.return_value = {
            "ok": True,
            "succeeded": 1,
            "total_targets": 2,
            "failed": 1,
        }
        await self.launch()
        self.assertFalse(self.director.last_result["ok"])
        self.assertEqual(self.director.active_banner["level"], "warn")
        self.assertIn("1/2", self.director.active_banner["subtitle"])

    async def test_failed_research_emits_no_delivery(self):
        self.hive.dispatch_harvest_swarm.return_value = {
            "succeeded": 0,
            "total_targets": 2,
            "failed": 2,
        }
        await self.launch()
        self.assertFalse(self.director.last_result["ok"])
        self.assertFalse(self.director.fx_events)

    async def test_unexpected_failure_is_visible(self):
        self.hive.dispatch_harvest_swarm.side_effect = RuntimeError("fixture")
        await self.launch()
        self.assertEqual(self.director.active_banner["phase"], "FAILED")

    async def test_empty_query_unknown_mode_and_stop_rejected(self):
        for mode, query in [("multi", ""), ("bogus", "topic")]:
            self.assertFalse((await self.director.run_live_mission(mode, query))["ok"])
        self.hive.emp.is_tripped = True
        self.assertFalse((await self.director.run_live_mission("multi", "topic"))["ok"])
        self.hive.dispatch_harvest_swarm.assert_not_called()

    async def test_overlapping_job_rejected(self):
        gate = asyncio.Event()

        async def wait(*args, **kwargs):
            await gate.wait()
            return {"succeeded": 2, "total_targets": 2}

        self.hive.dispatch_harvest_swarm.side_effect = wait
        self.assertTrue((await self.director.run_live_mission("multi", "topic"))["ok"])
        self.assertFalse((await self.director.run_live_mission("multi", "second"))["ok"])
        gate.set()
        await self.director._active_task

    async def test_cancelled_job_does_not_claim_completion(self):
        started = asyncio.Event()

        async def wait(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        self.hive.dispatch_harvest_swarm.side_effect = wait
        await self.director.run_live_mission("multi", "topic")
        await started.wait()
        self.director._active_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.director._active_task
        self.assertEqual(self.director.last_result, {"ok": False, "cancelled": True})

    async def test_integrity_mismatch_and_missing_coverage_not_green(self):
        for integrity in [{"intact": False, "roots": [{}]}, {"intact": True, "roots": []}]:
            self.hive.dispatch_task.side_effect = [{"ok": True}, integrity]
            await self.launch("security_audit", "")
            self.assertFalse(self.director.last_result["ok"])
        self.hive.dispatch_task.side_effect = [{"ok": True}, {"intact": True, "roots": [{}]}]
        await self.launch("security_audit", "")
        self.assertTrue(self.director.last_result["ok"])

    async def test_patrol_executes_actual_dispatch(self):
        state = types.SimpleNamespace(PATROLLING="idle")
        fn = load_method(
            "sentinel/core/hive.py",
            "SwarmHive",
            "_run_autonomous_patrol_sortie",
            {"SentinelState": state},
        )
        hive = types.SimpleNamespace(
            emp=self.hive.emp,
            simulator=self.director,
            _patrol_tick=0,
            units={
                name: types.SimpleNamespace(
                    caste=name, state="idle", pack_role="SOLO", unit_id=name
                )
                for name in ["warden", "tripwire"]
            },
            dispatch_task=AsyncMock(),
        )
        await fn(hive)
        self.assertEqual(hive.dispatch_task.call_args.args[0], "tripwire")
        await fn(hive)
        self.assertEqual(hive.dispatch_task.call_args.args[0], "warden")

    async def test_visual_neutralize_cannot_claim_containment(self):
        fn = load_method("sentinel/core/hive.py", "SwarmHive", "neutralize_target")
        result = await fn(object(), node_id="display-only")
        self.assertFalse(result["ok"])
        self.assertFalse(result["neutralized"])

    def test_retired_heal_never_accesses_files(self):
        for path, cls, name, args in [
            ("sentinel/core/hive.py", "SwarmHive", "heal_tripwire_roots", ()),
            ("sentinel/castes/tripwire.py", "TripwireCaste", "heal_root", ("fixture",)),
        ]:
            fn = load_method(path, cls, name)
            self.assertFalse(fn(object(), *args)["ok"])

    async def test_empty_failed_and_synthetic_harvests_cannot_succeed(self):
        names = [
            "VECTORING",
            "ENGAGED_HARVEST",
            "PATROLLING",
            "RETURNING",
            "NODE_SPAWNED",
            "NODE_UPDATED",
            "UNIT_STATE",
        ]
        constants = types.SimpleNamespace(**{name: name for name in names})
        fn = load_method(
            "sentinel/castes/harvester.py",
            "HarvesterCaste",
            "execute",
            {
                "SentinelState": constants,
                "EventTopic": constants,
                "asyncio": asyncio,
                "httpx": types.SimpleNamespace(HTTPError=RuntimeError),
                "BlockedUrlError": ValueError,
                "ET": types.SimpleNamespace(ParseError=ValueError),
            },
        )
        for action, upstream_ok, text in [
            ("arxiv", True, ""),
            ("arxiv", False, "content"),
            ("synthetic", True, "fake"),
        ]:
            node = types.SimpleNamespace(node_id="fixture", position=[0, 0, 0], to_dict=dict)
            worker = types.SimpleNamespace(
                _spawn_target_node=Mock(return_value=node),
                _harvest_arxiv=AsyncMock(return_value={"ok": upstream_ok, "text": text}),
                _sanitizer=types.SimpleNamespace(
                    execute=AsyncMock(return_value={"quarantined": False, "clean_text": text})
                ),
                descriptor=types.SimpleNamespace(caste_id="harvester"),
            )
            unit = types.SimpleNamespace(unit_id="fixture-unit", transition=Mock(), to_dict=dict)
            ledger = types.SimpleNamespace(
                mint=Mock(return_value=types.SimpleNamespace(to_dict=dict))
            )
            result = await fn(
                worker,
                unit,
                {"action": action, "query": "fixture", "animate": False},
                bus=types.SimpleNamespace(publish=AsyncMock()),
                ledger=ledger,
                nodes={},
            )
            self.assertFalse(result["ok"])
            for call in ledger.mint.call_args_list:
                self.assertFalse(call.kwargs["ok"])

    def test_python_sources_compile_without_importing(self):
        for path in (ROOT / "sentinel").rglob("*.py"):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")


if __name__ == "__main__":
    # Tests exercise pure coordinator logic with stubbed workers. Any accidental network fails.
    unittest.main(verbosity=2)
