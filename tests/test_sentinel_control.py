"""Command-bridge routes require the session token."""

from __future__ import annotations

from typing import Any


async def test_snapshot_and_overseer_post_require_the_session_token() -> None:
    """Most command-bridge routes used to skip the session token.

    GET /api/snapshot and Overseer POSTs (EMP, restore, scale, file read)
    answered any loopback caller. Only /api/command checked. One gate now
    covers every non-static route. Skipping that check on snapshot or on
    the POST path is a failure of this test.
    """
    import sys
    from pathlib import Path

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
