"""Caste 04: TripwireSentinel — Real-Time BLAKE2b Merkle Filesystem Integrity & Shadow Diff Guard."""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinel.castes.base import CasteDescriptor
from sentinel.core.bus import EventBus, EventTopic
from sentinel.core.fsm import SentinelState, SentinelUnit, WorldNode
from sentinel.core.receipts import ReceiptLedger
from sentinel.paths import quarantine_dir, repo_root

_IGNORED_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "data",
        "logs",
        "outputs",
        "harvests",
        "quarantine",
    }
)

_MAX_SHADOW_FILE_BYTES = 262_144  # 256 KiB per file in RAM shadow cache


@dataclass(frozen=True)
class RootBaseline:
    root_path: str
    label: str
    mode: str
    merkle_root: str
    file_hashes: dict[str, str]
    shadow_snapshots: dict[str, bytes] = field(default_factory=dict)
    shadow_total_bytes: int = 0


class TripwireCaste:
    """Narrow Caste 04: Computes BLAKE2b Merkle baselines, line-by-line forensic diffs, and reports changes."""

    descriptor = CasteDescriptor(
        caste_id="tripwire",
        code_prefix="TRP",
        title="Filesystem Merkle Tripwire",
        single_purpose="Guard protected directories via BLAKE2b Merkle snapshots, forensic diffs, and change alerts.",
        allowed_capabilities=frozenset(
            {"build_baseline", "verify_integrity", "register_watch_root", "heal_root"}
        ),
        version="1.1.0",
        orbit_radius=24.0,
        eye_color="#ffc08a",
        laser_kind="defense",
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = (config or {}).get("tripwire") or {}
        self.max_files_per_root = int(cfg.get("max_files_per_root", 5000))
        self._configured_roots: list[dict[str, Any]] = list(cfg.get("watched_roots") or [])
        self._baselines: dict[str, RootBaseline] = {}
        self._recorded_tamper_merkles: set[str] = set()

    def register_watch_root(
        self,
        path: str | Path,
        *,
        label: str = "",
        mode: str = "readonly_strict",
    ) -> RootBaseline:
        self.descriptor.assert_capability("register_watch_root")
        p = Path(path).resolve()
        key = str(p)
        file_hashes, merkle, shadows, total_bytes = self._scan_directory(p, capture_shadow=True)
        baseline = RootBaseline(
            root_path=key,
            label=label or p.name,
            mode=mode,
            merkle_root=merkle,
            file_hashes=file_hashes,
            shadow_snapshots=shadows,
            shadow_total_bytes=total_bytes,
        )
        self._baselines[key] = baseline
        return baseline

    def _scan_directory(
        self,
        root: Path,
        *,
        capture_shadow: bool = False,
    ) -> tuple[dict[str, str], str, dict[str, bytes], int]:
        self.descriptor.assert_capability("build_baseline")
        file_hashes: dict[str, str] = {}
        shadows: dict[str, bytes] = {}
        total_shadow_bytes = 0

        if not root.exists():
            return file_hashes, hashlib.blake2b(b"empty", digest_size=32).hexdigest(), shadows, 0

        if root.is_file():
            try:
                raw = root.read_bytes()
                digest = hashlib.blake2b(raw, digest_size=32).hexdigest()
                file_hashes[root.name] = digest
                if capture_shadow and len(raw) <= _MAX_SHADOW_FILE_BYTES:
                    shadows[root.name] = raw
                    total_shadow_bytes += len(raw)
            except OSError:
                pass
            return file_hashes, file_hashes.get(root.name, ""), shadows, total_shadow_bytes

        count = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in sorted(dirnames) if d not in _IGNORED_DIRS]
            for fname in sorted(filenames):
                if fname.endswith((".pyc", ".pyo", ".tmp")):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    rel = str(fpath.relative_to(root)).replace("\\", "/")
                    raw = fpath.read_bytes()
                    digest = hashlib.blake2b(raw, digest_size=32).hexdigest()
                    file_hashes[rel] = digest
                    if capture_shadow and len(raw) <= _MAX_SHADOW_FILE_BYTES:
                        shadows[rel] = raw
                        total_shadow_bytes += len(raw)
                    count += 1
                    if count >= self.max_files_per_root:
                        break
                except OSError:
                    continue
            if count >= self.max_files_per_root:
                break

        merkle_hasher = hashlib.blake2b(digest_size=32)
        for rel in sorted(file_hashes):
            merkle_hasher.update(f"{rel}:{file_hashes[rel]}\n".encode())
        return file_hashes, merkle_hasher.hexdigest(), shadows, total_shadow_bytes

    def initialize_configured_baselines(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for item in self._configured_roots:
            raw_path = str(item.get("path") or "").strip()
            if not raw_path:
                continue
            p = Path(raw_path).expanduser()
            if not p.is_absolute():
                p = repo_root() / p
            if not p.exists():
                continue
            b = self.register_watch_root(
                p,
                label=str(item.get("label") or p.name),
                mode=str(item.get("mode") or "hash_watch"),
            )
            summaries.append(
                {
                    "root_path": b.root_path,
                    "label": b.label,
                    "mode": b.mode,
                    "merkle_root": b.merkle_root,
                    "file_count": len(b.file_hashes),
                    "shadow_files": len(b.shadow_snapshots),
                    "shadow_kb": round(b.shadow_total_bytes / 1024.0, 1),
                }
            )
        return summaries

    def _compute_file_diff(self, baseline: RootBaseline, rel_path: str) -> list[str]:
        """Compute a unified line-by-line diff between the shadow cache and mutated disk file."""
        old_bytes = baseline.shadow_snapshots.get(rel_path)
        if old_bytes is None:
            return ["<binary or uncached file modified>"]
        root_p = Path(baseline.root_path)
        target_p = root_p if root_p.is_file() else (root_p / rel_path)
        new_bytes = b""
        if target_p.exists():
            try:
                new_bytes = target_p.read_bytes()
            except OSError:
                new_bytes = b""

        old_lines = old_bytes.decode("utf-8", errors="replace").splitlines()
        new_lines = new_bytes.decode("utf-8", errors="replace").splitlines()
        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"baseline/{rel_path}",
                tofile=f"disk/{rel_path}",
                lineterm="",
                n=2,
            )
        )
        return diff[:40]

    def verify_all(self) -> dict[str, Any]:
        """Compare current disk state against stored BLAKE2b Merkle baselines and compute diffs."""
        self.descriptor.assert_capability("verify_integrity")
        if not self._baselines and self._configured_roots:
            self.initialize_configured_baselines()

        reports: list[dict[str, Any]] = []
        all_intact = True

        for _key, baseline in list(self._baselines.items()):
            current_hashes, current_merkle, _, _ = self._scan_directory(
                Path(baseline.root_path), capture_shadow=False
            )
            modified: list[str] = []
            added: list[str] = []
            deleted: list[str] = []
            diffs: dict[str, list[str]] = {}
            forensic_file_path: str | None = None

            if current_merkle != baseline.merkle_root:
                all_intact = False
                for rel, old_h in baseline.file_hashes.items():
                    new_h = current_hashes.get(rel)
                    if new_h is None:
                        deleted.append(rel)
                        diffs[rel] = self._compute_file_diff(baseline, rel)
                    elif new_h != old_h:
                        modified.append(rel)
                        diffs[rel] = self._compute_file_diff(baseline, rel)
                for rel in current_hashes:
                    if rel not in baseline.file_hashes:
                        added.append(rel)

                # Write forensic tamper evidence to quarantine/ once per unique Merkle state
                sig = f"{baseline.root_path}:{current_merkle}"
                if sig not in self._recorded_tamper_merkles:
                    self._recorded_tamper_merkles.add(sig)
                    try:
                        q_dir = quarantine_dir()
                        q_path = q_dir / f"tripwire-tamper-{int(time.time())}-{current_merkle[:10]}.json"
                        payload = {
                            "timestamp": time.time(),
                            "root_path": baseline.root_path,
                            "label": baseline.label,
                            "mode": baseline.mode,
                            "baseline_merkle": baseline.merkle_root,
                            "current_merkle": current_merkle,
                            "modified": modified,
                            "added": added,
                            "deleted": deleted,
                            "unified_diffs": diffs,
                        }
                        q_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                        forensic_file_path = str(q_path)
                    except OSError:
                        pass

            reports.append(
                {
                    "root_path": baseline.root_path,
                    "label": baseline.label,
                    "mode": baseline.mode,
                    "intact": current_merkle == baseline.merkle_root,
                    "baseline_merkle": baseline.merkle_root[:16],
                    "current_merkle": current_merkle[:16],
                    "file_count": len(current_hashes),
                    "shadow_files": len(baseline.shadow_snapshots),
                    "shadow_kb": round(baseline.shadow_total_bytes / 1024.0, 1),
                    "modified": modified,
                    "added": added,
                    "deleted": deleted,
                    "diffs": diffs,
                    "forensic_file": forensic_file_path,
                }
            )

        return {"intact": all_intact, "roots": reports}

    def heal_root(self, root_path: str | Path) -> dict[str, Any]:
        """Reject legacy rollback calls without modifying watched files."""
        return {"ok": False, "error": "Runtime source restoration is disabled; integrity inspection remains available."}

    def apply_merkle_verdict(self, nodes: dict[str, WorldNode], verdict: dict[str, Any]) -> dict[str, Any]:
        """Create/update 3D Merkle Anchor Nodes in-place on the R=24 Tripwire Ring."""
        roots = verdict.get("roots") or []
        total = max(1, len(roots))
        for idx, r in enumerate(roots):
            angle = (idx / total) * (math.pi * 2.0)
            pos = [math.cos(angle) * 24.0, -3.5, math.sin(angle) * 24.0]
            node_id = f"merkle-root-{idx + 1}"
            intact = bool(r.get("intact", True))
            fcount = int(r.get("file_count", 0))
            mhash = str(r.get("current_merkle") or "")[:12]
            lbl_short = str(r.get("label") or f"Root-{idx + 1}")[:26]
            status_str = (
                f"MERKLE INTACT ({fcount} files)"
                if intact
                else f"MODIFIED ({len(r.get('modified', []))} files)"
            )
            meta_copy = dict(r)
            meta_copy["merkle_root"] = str(r.get("current_merkle") or "")
            existing = nodes.get(node_id)
            if existing is not None:
                existing.kind = "bastion" if intact else "threat"
                existing.label = f"MERKLE: {lbl_short} [{fcount}f • {mhash}]"
                existing.position = pos
                existing.status = status_str
                existing.progress = 1.0
                existing.severity = "none" if intact else "critical"
                existing.metadata = meta_copy
            else:
                nodes[node_id] = WorldNode(
                    node_id=node_id,
                    kind="bastion" if intact else "threat",
                    label=f"MERKLE: {lbl_short} [{fcount}f • {mhash}]",
                    position=pos,
                    status=status_str,
                    progress=1.0,
                    severity="none" if intact else "critical",
                    metadata=meta_copy,
                )
        return verdict

    def sync_merkle_nodes(self, nodes: dict[str, WorldNode]) -> dict[str, Any]:
        """Create/update 3D Merkle Anchor Nodes on the R=24 Tripwire Ring from real disk state."""
        verdict = self.verify_all()
        return self.apply_merkle_verdict(nodes, verdict)


    async def execute(
        self,
        unit: SentinelUnit,
        task_payload: dict[str, Any],
        *,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]:
        """Run a Tripwire integrity sweep or register a new protected directory."""
        action = str(task_payload.get("action") or "verify").strip().lower()
        animate = bool(task_payload.get("animate", True))

        if action == "register":
            target_path = str(task_payload.get("path") or "")
            label = str(task_payload.get("label") or "")
            baseline = await asyncio.to_thread(
                self.register_watch_root,
                target_path,
                label=label,
            )
            unit.missions_completed += 1
            receipt = ledger.mint(
                unit_id=unit.unit_id,
                caste=self.descriptor.caste_id,
                kind="tripwire",
                source=baseline.root_path,
                span=(
                    f"Registered Merkle baseline for {baseline.label}: "
                    f"{len(baseline.file_hashes)} files, root={baseline.merkle_root[:16]}"
                ),
                ok=True,
            )
            return {
                "ok": True,
                "root_path": baseline.root_path,
                "merkle_root": baseline.merkle_root,
                "file_count": len(baseline.file_hashes),
                "receipt": receipt.to_dict(),
            }

        verdict = await asyncio.to_thread(self.verify_all)
        unit.missions_completed += 1

        if not verdict["intact"]:
            unit.security_events += 1
            violated = [r for r in verdict["roots"] if not r["intact"]]
            first = violated[0]
            angle = (len(nodes) * 1.1) % (math.pi * 2.0)
            pos = [math.cos(angle) * 24.0, -3.5, math.sin(angle) * 24.0]
            alert_node = WorldNode(
                node_id=f"tripwire-alert-{int(asyncio.get_running_loop().time() * 1000)}",
                kind="threat",
                label=f"TRIPWIRE: {first['label'][:32]}",
                position=pos,
                status="integrity_mismatch",
                progress=1.0,
                severity="high",
                metadata=first,
            )
            nodes[alert_node.node_id] = alert_node
            unit.transition(
                SentinelState.ENGAGED_DEFENSE,
                task=f"Tripwire breached in {first['label']}",
                target_node_id=alert_node.node_id,
                target_position=pos,
                laser_active=True,
                laser_kind="defense",
            )
            await bus.publish(EventTopic.NODE_SPAWNED, alert_node.to_dict())
            await bus.publish(
                EventTopic.SECURITY_ALERT,
                {
                    "unit_id": unit.unit_id,
                    "caste": "tripwire",
                    "label": f"Merkle Mismatch: {first['label']}",
                    "details": first,
                },
            )
            await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())
            if animate:
                await asyncio.sleep(0.25)
            nodes.pop(alert_node.node_id, None)
            await bus.publish(EventTopic.NODE_REMOVED, {"node_id": alert_node.node_id})
            unit.transition(SentinelState.PATROLLING, task="Patrolling tripwire ring", laser_active=False)

        receipt = ledger.mint(
            unit_id=unit.unit_id,
            caste=self.descriptor.caste_id,
            kind="tripwire",
            source="merkle_watch_roots",
            span=(
                f"Merkle integrity sweep: intact={verdict['intact']} across "
                f"{len(verdict['roots'])} roots."
            ),
            ok=verdict["intact"],
            metadata=verdict,
        )
        await bus.publish(EventTopic.RECEIPT_MINTED, receipt.to_dict())
        return {
            "ok": verdict["intact"],
            "intact": verdict["intact"],
            "roots": verdict["roots"],
            "receipt": receipt.to_dict(),
        }
