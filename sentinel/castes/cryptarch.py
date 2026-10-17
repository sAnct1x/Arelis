"""CryptoVerifierCaste — Cryptographic Integrity, Shannon Entropy & Merkle Proof Sentinel."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import time
from typing import Any

from sentinel.castes.base import CasteDescriptor, CasteHandler
from sentinel.core.bus import EventBus
from sentinel.core.fsm import SentinelState, SentinelUnit, WorldNode
from sentinel.core.receipts import ReceiptLedger


def shannon_entropy(data: bytes) -> float:
    """Calculate Shannon entropy of byte data (0.0 to 8.0 bits per byte)."""
    if not data:
        return 0.0
    counts: dict[int, int] = {}
    for b in data:
        counts[b] = counts.get(b, 0) + 1
    total = len(data)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    return round(entropy, 4)


class CryptarchCaste(CasteHandler):
    """Narrow Sentinel caste specialized in cryptographic hash, HMAC, and entropy integrity audits."""

    descriptor = CasteDescriptor(
        caste_id="cryptarch",
        code_prefix="CRY",
        title="Cryptographic Cryptarch",
        single_purpose="Verifies cryptographic digests, HMAC authentication, Merkle tree branches, and Shannon entropy",
        allowed_capabilities=frozenset([
            "crypto:hash_verify",
            "crypto:hmac_validate",
            "crypto:merkle_proof",
            "crypto:entropy_calc",
        ]),
        version="1.1.0",
        orbit_radius=15.0,
        orbit_y_band=-1.5,
        speed_mult=1.0,
        eye_color="#e040fb",
        laser_kind="defense",
        doctrine="HUNTER-SEEKER",
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def verify_hash(
        self,
        data_bytes: bytes,
        expected_digest: str,
        algorithm: str = "sha256",
    ) -> dict[str, Any]:
        algo = algorithm.lower().replace("-", "")
        if algo == "sha256":
            actual = hashlib.sha256(data_bytes).hexdigest()
        elif algo in {"blake2b", "blake2"}:
            actual = hashlib.blake2b(data_bytes).hexdigest()
        elif algo == "sha512":
            actual = hashlib.sha512(data_bytes).hexdigest()
        elif algo == "sha1":
            actual = hashlib.sha1(data_bytes).hexdigest()
        else:
            return {"ok": False, "error": f"Unsupported hash algorithm: {algorithm!r}"}

        match = hmac.compare_digest(actual.lower(), expected_digest.strip().lower())
        return {
            "ok": match,
            "match": match,
            "algorithm": algo,
            "actual_digest": actual,
            "expected_digest": expected_digest,
            "bytes_length": len(data_bytes),
        }

    def validate_hmac(
        self,
        data_bytes: bytes,
        key_bytes: bytes,
        expected_hmac: str,
        algorithm: str = "sha256",
    ) -> dict[str, Any]:
        algo_name = algorithm.lower().replace("-", "")
        hash_fn = getattr(hashlib, algo_name, hashlib.sha256)
        mac = hmac.new(key_bytes, data_bytes, hash_fn).hexdigest()
        match = hmac.compare_digest(mac.lower(), expected_hmac.strip().lower())
        return {
            "ok": match,
            "match": match,
            "actual_hmac": mac,
            "expected_hmac": expected_hmac,
        }

    def inspect_entropy(self, data_bytes: bytes, threshold: float = 7.2) -> dict[str, Any]:
        entropy = shannon_entropy(data_bytes)
        suspicious = entropy >= threshold and len(data_bytes) >= 128
        return {
            "ok": not suspicious,
            "entropy": entropy,
            "threshold": threshold,
            "suspicious_packed_or_encrypted": suspicious,
            "bytes_length": len(data_bytes),
        }

    def verify_merkle_proof(
        self,
        data_bytes: bytes,
        root_hash: str,
        proof_path: list[dict[str, str]] | None = None,
        algorithm: str = "sha256",
    ) -> dict[str, Any]:
        """Cryptographically verify a Merkle tree leaf inclusion proof against root_hash."""
        algo = algorithm.lower().replace("-", "")
        hash_fn = getattr(hashlib, algo, hashlib.sha256)
        curr = hash_fn(data_bytes).hexdigest()

        path = proof_path or []
        for step in path:
            sibling = str(step.get("hash") or "")
            pos = str(step.get("position") or "right").lower()
            if pos == "left":
                combined = (sibling + curr).encode("utf-8")
            else:
                combined = (curr + sibling).encode("utf-8")
            curr = hash_fn(combined).hexdigest()

        match = hmac.compare_digest(curr.lower(), root_hash.strip().lower()) if root_hash else True
        return {
            "ok": match,
            "match": match,
            "leaf_hash": hash_fn(data_bytes).hexdigest(),
            "computed_root": curr,
            "expected_root": root_hash,
            "steps_verified": len(path),
        }


    async def execute(
        self,
        unit: SentinelUnit,
        task_payload: dict[str, Any],
        *,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]:
        op = str(task_payload.get("capability") or task_payload.get("action") or "crypto:hash_verify").strip()
        self.descriptor.assert_capability(op)

        raw_data = task_payload.get("data") or task_payload.get("content") or ""
        if isinstance(raw_data, str):
            data_bytes = raw_data.encode("utf-8", errors="replace")
        elif isinstance(raw_data, bytes):
            data_bytes = raw_data
        else:
            data_bytes = str(raw_data).encode("utf-8")

        target_name = str(task_payload.get("target") or "payload-digest")[:64]

        # 1. State machine transitions
        unit.transition(
            SentinelState.VECTORING,
            task=f"[CRYPTO] Vectoring -> {target_name}",
            target_position=[10.0, -1.5, 10.0],
        )
        await asyncio.sleep(0.04)

        unit.transition(
            SentinelState.ENGAGED_EXECUTION,
            task=f"[CRYPTO] Executing {op} -> {target_name}",
            laser_active=True,
            laser_kind=self.descriptor.laser_kind,
        )

        t0 = time.perf_counter()
        result: dict[str, Any] = {}

        if op == "crypto:hash_verify":
            expected = str(task_payload.get("expected") or task_payload.get("digest") or "")
            algo = str(task_payload.get("algorithm") or "sha256")
            result = await asyncio.to_thread(self.verify_hash, data_bytes, expected, algo)

        elif op == "crypto:hmac_validate":
            key_str = str(task_payload.get("key") or "")
            expected_hmac = str(task_payload.get("expected_hmac") or "")
            algo = str(task_payload.get("algorithm") or "sha256")
            result = await asyncio.to_thread(
                self.validate_hmac,
                data_bytes,
                key_str.encode("utf-8"),
                expected_hmac,
                algo,
            )

        elif op == "crypto:entropy_calc":
            thresh = float(task_payload.get("threshold", 7.2))
            result = await asyncio.to_thread(self.inspect_entropy, data_bytes, thresh)

        elif op == "crypto:merkle_proof":
            root_hash = str(task_payload.get("root") or "")
            proof_path = list(task_payload.get("proof_path") or [])
            algo = str(task_payload.get("algorithm") or "sha256")
            result = await asyncio.to_thread(self.verify_merkle_proof, data_bytes, root_hash, proof_path, algo)


        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        unit.missions_completed += 1
        unit.bytes_processed += len(data_bytes)

        # 2. Return to patrol
        unit.transition(
            SentinelState.RETURNING,
            task=f"[CRYPTO] Completed {op}",
            laser_active=False,
        )
        await asyncio.sleep(0.02)
        unit.transition(
            SentinelState.PATROLLING,
            task="Patrolling cryptarch sector",
            laser_active=False,
        )

        ok = bool(result.get("ok", True))
        receipt = ledger.mint(
            unit_id=unit.unit_id,
            caste=self.descriptor.caste_id,
            kind="defense",
            source=f"sentinel://crypto/{op}",
            span=f"Crypto Sentinel verified {op} on {target_name} (ok={ok}, duration={duration_ms}ms)",
            ok=ok,
            metadata={
                "target": target_name,
                "capability": op,
                "duration_ms": duration_ms,
                "details": result,
            },
        )

        return {
            "ok": ok,
            "caste": self.descriptor.caste_id,
            "unit_id": unit.unit_id,
            "capability": op,
            "duration_ms": duration_ms,
            "result": result,
            "receipt": receipt.to_dict(),
        }


CryptoVerifierCaste = CryptarchCaste

__all__ = ["CryptarchCaste", "CryptoVerifierCaste", "shannon_entropy"]
