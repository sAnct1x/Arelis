"""CLI & Desktop Entrypoint for Sentinel (Arelis_Sentinel)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from sentinel.bridge.client import SentinelClient
from sentinel.bridge.server import SentinelBridgeServer
from sentinel.config import load_config
from sentinel.core.hive import SwarmHive
from sentinel.ui.window import launch_overseer_window


async def _run_headless(config: dict) -> int:
    hive = SwarmHive(config)
    bridge_cfg = config.get("bridge") or {}
    server = SentinelBridgeServer(
        hive,
        host=str(bridge_cfg.get("host", "127.0.0.1")),
        preferred_port=int(bridge_cfg.get("port", 8790)),
        telemetry_hz=int(bridge_cfg.get("telemetry_hz", 30)),
    )
    await server.start()
    print(f"SENTINEL HIVE ONLINE -> {server.overseer_url}")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await server.stop()
    return 0


async def _run_cli_action(args: argparse.Namespace, port: int) -> int:
    client = SentinelClient(port=port)
    if args.status:
        res = await client.snapshot()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if args.emp:
        res = await client.emp_halt(reason="CLI Emergency EMP Trigger")
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if args.restore:
        res = await client.emp_restore()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if args.demo_wave:
        res = await client.command("arelis_demo_wave")
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="SENTINEL — Autonomous Narrow-Caste Swarm & 3D Overseer for Arelis",
    )
    parser.add_argument("--headless", action="store_true", help="Run Hive + Bridge daemon without opening GUI window")
    parser.add_argument("--theme", choices=["sodium", "filament", "night", "matrix"], help="Initial 3D Overseer theme")
    parser.add_argument("--port", type=int, help="Override preferred loopback port (default: 8790)")
    parser.add_argument("--status", action="store_true", help="Print live snapshot from running Sentinel Hive")
    parser.add_argument("--demo-wave", action="store_true", help="Legacy demo command (retired; returns an error)")
    parser.add_argument("--emp", action="store_true", help="Trigger immediate hardware EMP Kill-Switch")
    parser.add_argument("--restore", action="store_true", help="Restore swarm from EMP lockout")

    args = parser.parse_args(argv)
    if sys.stderr is None or sys.stdout is None:
        from sentinel.paths import logs_dir

        log_file = logs_dir() / "desktop_app.log"
        logging.basicConfig(
            filename=str(log_file),
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        )

    config = load_config()
    if args.theme:
        config.setdefault("ui", {})["theme"] = args.theme
    if args.port:
        config.setdefault("bridge", {})["port"] = args.port

    port = int((config.get("bridge") or {}).get("port", 8790))

    if args.status or args.emp or args.restore or args.demo_wave:
        return asyncio.run(_run_cli_action(args, port))

    if args.headless:
        return asyncio.run(_run_headless(config))

    return launch_overseer_window(config)


if __name__ == "__main__":
    sys.exit(main())
