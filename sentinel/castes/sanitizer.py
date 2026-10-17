"""Caste 03: SanitizerSentinel — Multi-Stage Payload, Polyglot & Prompt-Injection Decontamination."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from sentinel.castes.base import CasteDescriptor
from sentinel.core.bus import EventBus, EventTopic
from sentinel.core.fsm import SentinelState, SentinelUnit, WorldNode
from sentinel.core.receipts import ReceiptLedger, sha256_hex
from sentinel.paths import immunized_hashes_path, quarantine_dir
from sentinel.safety.redact import InjectionFinding, SanitizeReport, inspect_and_sanitize_text

# Known binary magic signatures for MIME/extension spoofing & polyglot detection
_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"PK\x03\x04", "application/zip"),
    (b"MZ", "application/x-dosexec"),
    (b"\x7fELF", "application/x-elf"),
    (b"\xfe\xed\xfa\xce", "application/x-mach-binary"),
    (b"\xfe\xed\xfa\xcf", "application/x-mach-binary"),
    (b"\xcf\xfa\xed\xfe", "application/x-mach-binary"),
    (b"#!", "application/x-sh"),
    (b"<?php", "application/x-php"),
)

_EXECUTABLE_MIMES = frozenset(
    {
        "application/x-dosexec",
        "application/x-elf",
        "application/x-mach-binary",
        "application/x-sh",
        "application/x-php",
    }
)


class SanitizerCaste:
    """Narrow Caste 03: Inspects text, HTML, and files; immunizes SHA-256 threat signatures."""

    descriptor = CasteDescriptor(
        caste_id="sanitizer",
        code_prefix="SAN",
        title="Payload Sanitizer",
        single_purpose="Decontaminate untrusted text, HTML, and files; neutralize prompt injections, scrub secrets, and immunize threat hashes.",
        allowed_capabilities=frozenset(
            {"sanitize_text", "sanitize_html", "verify_binary", "inspect_archive", "quarantine_payload", "immunize_hash"}
        ),

        version="1.2.0",
        orbit_radius=12.5,
        eye_color="#52e5a8",
        laser_kind="sanitize",
    )

    def __init__(self, config: dict[str, Any] | None = None, *, immunized_file: Path | None = None) -> None:
        cfg = (config or {}).get("sanitizer") or {}
        ret_cfg = (config or {}).get("retention") or {}
        self.max_payload_bytes = int(cfg.get("max_payload_bytes", 5_242_880))
        self.quarantine_on_injection = bool(cfg.get("quarantine_on_injection", True))
        self.max_quarantine_files = int(ret_cfg.get("max_quarantine_files", 25))
        self._immunized_path = immunized_file or immunized_hashes_path()
        self._lock = threading.Lock()
        self._immunized_hashes: dict[str, dict[str, Any]] = {}
        self._load_immunized_hashes()

    def prune_quarantine_files(self, max_keep: int | None = None) -> list[str]:
        """Keep the latest max_keep quarantine forensics in data/quarantine/ and remove older ones."""
        keep = max_keep if max_keep is not None else self.max_quarantine_files
        qdir = quarantine_dir()
        if not qdir.is_dir():
            return []
        try:
            files = sorted(qdir.glob("quarantine-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            removed: list[str] = []
            for f in files[keep:]:
                f.unlink(missing_ok=True)
                removed.append(f.name)
            return removed
        except OSError:
            return []

    def _load_immunized_hashes(self) -> None:
        if not self._immunized_path.is_file():
            return
        with contextlib.suppress(OSError, ValueError, TypeError):
            data = json.loads(self._immunized_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                with self._lock:
                    for k, v in data.items():
                        if isinstance(k, str) and isinstance(v, dict):
                            self._immunized_hashes[k] = v

    def _save_immunized_hashes_locked(self) -> None:
        with contextlib.suppress(OSError):
            self._immunized_path.parent.mkdir(parents=True, exist_ok=True)
            self._immunized_path.write_text(
                json.dumps(self._immunized_hashes, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    @property
    def immunized_count(self) -> int:
        with self._lock:
            return len(self._immunized_hashes)

    def list_immunized_hashes(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._immunized_hashes.values())[-16:]

    def immunize_hash(
        self,
        digest: str,
        *,
        source: str = "manual",
        reason: str = "Hostile payload signature",
        unit_id: str = "SNT-SAN-001",
    ) -> dict[str, Any]:
        """Permanently record a hostile payload SHA-256 signature for O(1) instant kill on repeat contact."""
        self.descriptor.assert_capability("immunize_hash")
        clean_hash = (digest or "").strip().lower()
        if not clean_hash:
            raise ValueError("Empty SHA-256 digest cannot be immunized")
        with self._lock:
            existing = self._immunized_hashes.get(clean_hash)
            entry = {
                "sha256": clean_hash,
                "source": source[:160],
                "reason": reason[:200],
                "unit_id": unit_id,
                "immunized_at": existing["immunized_at"] if existing else int(time.time()),
                "hits_blocked": int(existing.get("hits_blocked", 0)) + 1 if existing else 1,
            }
            self._immunized_hashes[clean_hash] = entry
            self._save_immunized_hashes_locked()
        return entry

    def check_immunized(self, raw_data: str | bytes) -> dict[str, Any] | None:
        """Return the immunization record if raw_data (or a 64-char hex SHA-256) matches a known-bad signature."""
        if (
            isinstance(raw_data, str)
            and len(raw_data) == 64
            and all(c in "0123456789abcdefABCDEF" for c in raw_data)
        ):
            digest = raw_data.lower()
        else:
            digest = sha256_hex(raw_data).lower()
        with self._lock:
            entry = self._immunized_hashes.get(digest)
            if entry is not None:
                entry["hits_blocked"] = int(entry.get("hits_blocked", 0)) + 1
                self._save_immunized_hashes_locked()
                return dict(entry)
        return None

    def verify_magic_bytes(self, data: bytes, declared_ext: str = "") -> dict[str, Any]:
        self.descriptor.assert_capability("verify_binary")
        detected_mime = "text/plain"
        for sig, mime in _MAGIC_SIGNATURES:
            if data.startswith(sig):
                detected_mime = mime
                break
        ext = (declared_ext or "").lower().lstrip(".")
        executable_trap = detected_mime in _EXECUTABLE_MIMES

        # Also inspect the first 4096 bytes for embedded polyglot traps (e.g. MZ or <script> inside PDF/image)
        head_window = data[:4096]
        polyglot_embedded = False
        if not executable_trap and (
            b"MZ\x90\x00" in head_window[2:]
            or b"\x7fELF" in head_window[4:]
            or b"<script" in head_window.lower()
            or b"powershell -enc" in head_window.lower()
        ):
            polyglot_embedded = True
            executable_trap = True

        mismatch = False
        if ext in {"txt", "md", "html", "json", "csv", "pdf", "png", "jpg"} and (
            detected_mime in _EXECUTABLE_MIMES
            or (ext in {"txt", "md", "html", "json", "csv"} and detected_mime == "application/zip")
            or (ext == "pdf" and detected_mime != "application/pdf")
        ):
            mismatch = True
        return {
            "detected_mime": detected_mime,
            "declared_ext": ext,
            "executable_trap": executable_trap,
            "polyglot_embedded": polyglot_embedded,
            "mime_mismatch": mismatch,
            "safe_binary": not (executable_trap or mismatch),
        }

    def inspect_archive_safety(
        self,
        data_bytes: bytes,
        *,
        max_total_bytes: int = 50_000_000,
        max_ratio: float = 100.0,
    ) -> dict[str, Any]:
        """Audit ZIP/archive headers against decompression bombs, path traversals, and nested traps."""
        self.descriptor.assert_capability("inspect_archive")
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(data_bytes)) as zf:
                total_uncompressed = 0
                compressed_size = max(1, len(data_bytes))
                suspicious_entries: list[str] = []

                for info in zf.infolist():
                    if ".." in info.filename or info.filename.startswith("/") or info.filename.startswith("\\"):
                        suspicious_entries.append(f"path_traversal: {info.filename}")
                    total_uncompressed += info.file_size

                ratio = total_uncompressed / compressed_size
                is_bomb = ratio > max_ratio or total_uncompressed > max_total_bytes

                return {
                    "ok": not is_bomb and len(suspicious_entries) == 0,
                    "is_decompression_bomb": is_bomb,
                    "compression_ratio": round(ratio, 2),
                    "total_uncompressed_bytes": total_uncompressed,
                    "compressed_bytes": compressed_size,
                    "entries_count": len(zf.filelist),
                    "suspicious_entries": suspicious_entries,
                }
        except zipfile.BadZipFile:
            return {"ok": True, "not_a_zip": True}
        except (ValueError, KeyError, RuntimeError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def quarantine_payload(

        self,
        *,
        source: str,
        raw_text: str,
        report: SanitizeReport,
        unit_id: str,
    ) -> Path:
        self.descriptor.assert_capability("quarantine_payload")
        qdir = quarantine_dir()
        full_sha = sha256_hex(raw_text)
        digest = full_sha[:12]
        stamp = int(time.time())
        target = qdir / f"quarantine-{stamp}-{digest}.json"
        findings_list = [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "matched_span": f.matched_span,
                "offset": f.offset,
            }
            for f in report.findings
        ]
        # Immunize the payload hash so any repeat submission is killed in O(1)
        rule_summary = ", ".join(f.rule_id for f in report.findings) or "quarantined_payload"
        self.immunize_hash(
            full_sha,
            source=source,
            reason=f"Quarantined ({report.max_severity}): {rule_summary}",
            unit_id=unit_id,
        )
        record = {
            "quarantined_at": stamp,
            "unit_id": unit_id,
            "source": source,
            "sha256": full_sha,
            "immunized": True,
            "max_severity": report.max_severity,
            "findings": findings_list,
            "raw_preview": raw_text[:2000],
        }
        target.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        self.prune_quarantine_files()
        return target

    async def execute(
        self,
        unit: SentinelUnit,
        task_payload: dict[str, Any],
        *,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]:
        """Run O(1) SHA-256 immunization check + 3-stage sanitization with 3D kinematics updates."""
        raw_text = str(task_payload.get("text") or "")
        source = str(task_payload.get("source") or "inline_payload")
        is_html = bool(task_payload.get("is_html", False))
        node_id = task_payload.get("node_id")
        animate = bool(task_payload.get("animate", True))

        cap = str(task_payload.get("capability") or ("sanitize_html" if is_html else "sanitize_text")).strip()
        self.descriptor.assert_capability(cap)

        if cap == "inspect_archive":
            raw_data = task_payload.get("data") or task_payload.get("bytes") or b""
            data_bytes = raw_data.encode() if isinstance(raw_data, str) else raw_data
            audit_res = self.inspect_archive_safety(data_bytes)
            unit.missions_completed += 1
            unit.bytes_processed += len(data_bytes)
            receipt = ledger.mint(
                unit_id=unit.unit_id,
                caste="sanitizer",
                kind="sanitize",
                source=f"sentinel://sanitizer/archive/{source}",
                span=f"Archive Inspection on {source} (ok={audit_res.get('ok')}, is_bomb={audit_res.get('is_decompression_bomb', False)})",
                ok=bool(audit_res.get("ok")),
                metadata=audit_res,
            )
            return {
                "ok": bool(audit_res.get("ok")),
                "caste": "sanitizer",
                "unit_id": unit.unit_id,
                "capability": cap,
                "archive_audit": audit_res,
                "receipt": receipt.to_dict(),
            }

        target_pos = [0.0, 4.0, 12.0]
        if node_id and node_id in nodes:
            target_pos = list(nodes[node_id].position)

        unit.transition(
            SentinelState.ENGAGED_SANITIZE,
            task=f"Scanning payload from {source[:48]}",
            target_node_id=node_id,
            target_position=target_pos,
            laser_active=True,
            laser_kind="sanitize",
        )

        await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())

        if animate:
            await asyncio.sleep(0.65)

        # Stage 0: Check O(1) Known-Bad Payload SHA-256 Immunization Ledger
        imm_hit = self.check_immunized(raw_text)
        if imm_hit is not None:
            imm_finding = InjectionFinding(
                rule_id="immunized_known_threat_sha256",
                severity="critical",
                matched_span=f"SHA-256 {imm_hit['sha256'][:16]}... previously quarantined ({imm_hit.get('reason', '')})",
                offset=0,
            )
            report = SanitizeReport(
                clean_text="[BLOCKED: IMMUNIZED THREAT PAYLOAD SHA-256]",
                safe=False,
                quarantined=True,
                redacted_secrets_count=0,
                hidden_blocks_stripped=0,
                zero_width_stripped=0,
                findings=(imm_finding,),
            )
        else:
            report = inspect_and_sanitize_text(
                raw_text[: self.max_payload_bytes],
                is_html=is_html,
                quarantine_on_high=self.quarantine_on_injection,
            )

        unit.bytes_processed += len(raw_text.encode("utf-8", errors="ignore"))
        unit.missions_completed += 1

        q_path: str | None = None
        if report.quarantined:
            unit.security_events += 1
            saved = self.quarantine_payload(
                source=source,
                raw_text=raw_text,
                report=report,
                unit_id=unit.unit_id,
            )
            q_path = str(saved)
            q_node_id = node_id or f"quarantine-{int(time.time() * 1000)}"
            q_node = WorldNode(
                node_id=q_node_id,
                kind="quarantine",
                label=f"QUARANTINED: {source[:36]}",
                position=target_pos,
                status="quarantined",
                progress=1.0,
                severity=report.max_severity,
                metadata={
                    "source": source,
                    "sha256": sha256_hex(raw_text),
                    "immunized": True,
                    "findings": [f.rule_id for f in report.findings],
                    "quarantine_file": q_path,
                },
            )
            nodes[q_node_id] = q_node
            unit.transition(
                SentinelState.QUARANTINING,
                task=f"Containing hostile payload ({report.max_severity})",
                target_node_id=q_node_id,
                target_position=target_pos,
                laser_active=True,
                laser_kind="defense",
            )
            await bus.publish(
                EventTopic.PAYLOAD_QUARANTINED,
                {
                    "unit_id": unit.unit_id,
                    "source": source,
                    "severity": report.max_severity,
                    "findings": [f.rule_id for f in report.findings],
                    "quarantine_path": q_path,
                    "node": q_node.to_dict(),
                },
            )
        else:
            unit.transition(
                SentinelState.PATROLLING,
                task="Patrolling sanitizer ring",
                laser_active=False,
                carrying_orb=False,
            )

        receipt = ledger.mint(
            unit_id=unit.unit_id,
            caste=self.descriptor.caste_id,
            kind="sanitize",
            source=source,
            span=(
                f"Sanitized ({len(raw_text)} chars): safe={report.safe}, "
                f"quarantined={report.quarantined}, secrets_redacted={report.redacted_secrets_count}, "
                f"hidden_stripped={report.hidden_blocks_stripped}"
            ),
            ok=not report.quarantined,
            raw_content=report.clean_text,
            metadata={
                "safe": report.safe,
                "quarantined": report.quarantined,
                "immunized_hit": imm_hit is not None,
                "max_severity": report.max_severity,
                "findings": [f.rule_id for f in report.findings],
                "quarantine_path": q_path,
            },
        )
        await bus.publish(EventTopic.RECEIPT_MINTED, receipt.to_dict())
        await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())

        return {
            "ok": not report.quarantined,
            "safe": report.safe,
            "quarantined": report.quarantined,
            "immunized": report.quarantined,
            "immunized_hit": imm_hit is not None,
            "clean_text": report.clean_text,
            "max_severity": report.max_severity,
            "redacted_secrets_count": report.redacted_secrets_count,
            "hidden_blocks_stripped": report.hidden_blocks_stripped,
            "zero_width_stripped": report.zero_width_stripped,
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "matched_span": f.matched_span,
                }
                for f in report.findings
            ],
            "quarantine_path": q_path,
            "receipt": receipt.to_dict(),
        }
