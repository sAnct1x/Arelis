"""Sovereign Arelis Client for Commanding the Sentinel Swarm over Loopback."""

from __future__ import annotations

from typing import Any

import httpx

from sentinel.bridge.protocol import assert_loopback_host, command_headers, ensure_session_token


class SentinelClient:
    """Async client used by Arelis (or CLI tools) to command the Sentinel Hive."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8790,
        token: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.host = assert_loopback_host(host)
        self.port = int(port)
        self.token = token or ensure_session_token()
        self.timeout_s = timeout_s

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def command(self, op: str, **kwargs: Any) -> dict[str, Any]:
        payload = {"op": op, **kwargs}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(
                f"{self.base_url}/api/command",
                json=payload,
                headers=command_headers(self.token),
            )
            return resp.json()

    async def ping(self) -> dict[str, Any]:
        return await self.command("ping")

    async def snapshot(self) -> dict[str, Any]:
        return await self.command("snapshot")

    async def spawn_units(self, caste: str, count: int = 1, *, tier: str = "mk1") -> dict[str, Any]:
        return await self.command("spawn_units", caste=caste, count=count, tier=tier)

    async def scale_caste(self, caste: str, target_count: int, *, tier: str = "mk1") -> dict[str, Any]:
        return await self.command("scale_caste", caste=caste, target_count=target_count, tier=tier)

    async def upgrade_unit(self, unit_id: str, tier: str = "mk2", *, version: str | None = None) -> dict[str, Any]:
        return await self.command("upgrade_unit", unit_id=unit_id, tier=tier, version=version)

    async def upgrade_caste(self, caste: str, tier: str = "mk2", *, version: str | None = None) -> dict[str, Any]:
        return await self.command("upgrade_caste", caste=caste, tier=tier, version=version)

    async def deploy_harvest_swarm(
        self,
        question: str,
        targets: list[dict[str, Any]],
        *,
        save_report: bool = True,
        animate: bool = True,
    ) -> dict[str, Any]:
        return await self.command(
            "deploy_harvest_swarm",
            question=question,
            targets=targets,
            save_report=save_report,
            animate=animate,
        )

    async def dispatch_task(
        self,
        caste: str,
        payload: dict[str, Any],
        *,
        unit_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.command("dispatch_task", caste=caste, payload=payload, unit_id=unit_id)

    async def set_theme(self, theme: str) -> dict[str, Any]:
        return await self.command("set_theme", theme=theme)

    async def emp_halt(self, reason: str = "Arelis Sovereign EMP Halt") -> dict[str, Any]:
        return await self.command("emp_halt", reason=reason)

    async def emp_restore(self) -> dict[str, Any]:
        return await self.command("emp_restore")

    async def register_caste(
        self,
        caste_id: str,
        *,
        code_prefix: str | None = None,
        title: str | None = None,
        single_purpose: str | None = None,
        allowed_capabilities: list[str] | None = None,
        orbit_radius: float = 20.0,
        orbit_y_band: float = 0.0,
        speed_mult: float = 1.0,
        eye_color: str = "#00e5ff",
        laser_kind: str = "harvest",
        doctrine: str = "HUNTER-SEEKER",
        rules: list[dict[str, Any]] | None = None,
        initial_pool: int = 0,
        tier: str = "mk1",
    ) -> dict[str, Any]:
        return await self.command(
            "register_caste",
            caste_id=caste_id,
            code_prefix=code_prefix,
            title=title,
            single_purpose=single_purpose,
            allowed_capabilities=allowed_capabilities,
            orbit_radius=orbit_radius,
            orbit_y_band=orbit_y_band,
            speed_mult=speed_mult,
            eye_color=eye_color,
            laser_kind=laser_kind,
            doctrine=doctrine,
            rules=rules,
            initial_pool=initial_pool,
            tier=tier,
        )

    async def unregister_caste(self, caste_id: str) -> dict[str, Any]:
        return await self.command("unregister_caste", caste_id=caste_id)

    async def list_castes(self) -> dict[str, Any]:
        return await self.command("list_castes")

    async def neutralize_target(
        self,
        *,
        node_id: str | None = None,
        ip: str | None = None,
        sha256: str | None = None,
        reason: str = "Sovereign Hunter-Killer Neutralization",
    ) -> dict[str, Any]:
        return await self.command("neutralize_target", node_id=node_id, ip=ip, sha256=sha256, reason=reason)

    async def prune_storage(self) -> dict[str, Any]:
        return await self.command("prune_storage")

    async def get_authority_status(self) -> dict[str, Any]:
        return await self.command("authority_status")

    async def operator_sign_off(self, request_id: str, *, approve: bool = True) -> dict[str, Any]:
        return await self.command("operator_sign_off", request_id=request_id, approve=approve)


