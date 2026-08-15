"""Per-turn latency log for chat and voice.

Voice already has a state-machine trace under voice.debug. This is different:
every agent turn (typed or spoken) writes stage timings to logs/turns.log so
you can see whether a pause was summarize, the model, a tool, confirm wait,
or STT — without turning on a special debug flag.

One line per stage, plus a done summary:

    turn 02:01:15.123 start     id=a1b2c3d4 session=… source=voice role=fast speak=1 chars=28
    turn 02:01:16.900 summarize id=a1b2c3d4 ms=1770 dropped=4
    turn 02:01:19.400 round     id=a1b2c3d4 n=1 ms=2500 kind=tools calls=1
    turn 02:01:19.420 tool      id=a1b2c3d4 name=send_sms ms=18 ok=1
    turn 02:01:21.100 done      id=a1b2c3d4 total_ms=5970 model_ms=2500 summarize_ms=1770 …

``ttft_ms`` / first_token is agent-felt (first painted ASSISTANT_DELTA), not
Ollama engine TTFT. Engine prefill/decode live on ``ollama_metrics`` lines and
``model_prefill_ms`` / ``model_decode_ms`` on ``done``.

Off only when agent.turn_telemetry is false. Cheap when disabled.
Bus-level audit (confirms, SMS, errors) lives in logs/events.log.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from arelis.config import PROJECT_ROOT

log = logging.getLogger("arelis.turn.trace")

_HANDLER_TAG = "arelis-turn-trace"
_attached = False


def ollama_ns_to_ms(value: Any) -> int | None:
    """Convert Ollama nanosecond duration fields to integer milliseconds."""
    if value is None:
        return None
    try:
        ns = int(value)
    except (TypeError, ValueError):
        return None
    if ns < 0:
        return None
    return int(ns / 1_000_000)


def turn_telemetry_enabled(config: dict[str, Any] | None) -> bool:
    agent = (config or {}).get("agent") or {}
    return bool(agent.get("turn_telemetry", True))


def ensure_turn_log(log_dir: Path | None = None) -> None:
    """Attach the rotating turns.log handler once per process."""
    global _attached
    if _attached:
        return
    directory = log_dir or PROJECT_ROOT / "logs"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(
            directory / "turns.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._arelis_tag = _HANDLER_TAG  # type: ignore[attr-defined]
    # Avoid doubling if something re-called ensure.
    for existing in log.handlers:
        if getattr(existing, "_arelis_tag", "") == _HANDLER_TAG:
            _attached = True
            return
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    _attached = True


def log_span(event: str, *, turn_id: str = "-", session_id: str = "", **fields: Any) -> None:
    """Log a one-off span (e.g. STT). Pass turn_id/session_id when known."""
    ensure_turn_log()
    if session_id:
        fields = {"session": session_id, **fields}
    # Prefer an explicit span id so STT lines are searchable even without a turn.
    if "span" not in fields:
        fields = {"span": uuid4().hex[:8], **fields}
    log.info(_format(event, fields, turn_id=turn_id or "-"))


class TurnTimer:
    """Accumulates stage timings for one agent turn."""

    def __init__(
        self,
        *,
        source: str,
        role: str,
        speak: bool,
        user_chars: int,
        enabled: bool = True,
        session_id: str = "",
        route_reason: str = "default",
        user_text: str = "",
    ) -> None:
        self.enabled = bool(enabled)
        self.id = uuid4().hex[:8]
        self.session_id = (session_id or "").strip() or "-"
        self.source = source or "chat"
        self.role = role
        self.route_reason = (route_reason or "default").strip() or "default"
        self.speak = bool(speak)
        self.user_chars = int(user_chars)
        self.user_preview = _clip_preview(user_text)
        self._t0 = time.perf_counter()
        self._first_delta_at: float | None = None
        self.summarize_ms = 0
        self.model_ms = 0
        self.model_prefill_ms = 0
        self.model_decode_ms = 0
        self.tool_ms = 0
        self.confirm_ms = 0
        self.rounds = 0
        self.tools: list[str] = []
        self.tool_records: list[dict[str, Any]] = []
        # Which deterministic gates fired, and what they did about it. These were
        # written to the text log only, so the one record that survives rotation
        # could say which tools ran but never why — and "is this gate still
        # reachable?" is the question the whole gate layer turns on. Answering it
        # meant re-deriving turn ids out of turns.log, which retains a fraction of
        # the turns turns.jsonl does.
        self.gate_records: list[dict[str, Any]] = []
        self.round_ms_by_n: dict[int, int] = {}
        self.last_prompt_eval_count: int | None = None
        self.last_eval_count: int | None = None
        self.history_kept: int | None = None
        self.history_dropped: int | None = None
        if self.enabled:
            ensure_turn_log()
            start_fields: dict[str, Any] = {
                "session": self.session_id,
                "source": self.source,
                "role": self.role,
                "route_reason": self.route_reason,
                "speak": self.speak,
                "chars": self.user_chars,
            }
            self.mark("start", **start_fields)

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)

    def mark(self, event: str, **fields: Any) -> None:
        if event == "round":
            try:
                n = int(fields.get("n") or 0)
                ms = int(fields.get("ms") or 0)
            except (TypeError, ValueError):
                n, ms = 0, 0
            if n > 0:
                self.round_ms_by_n[n] = ms
        if event == "tool":
            rec: dict[str, Any] = {
                "name": str(fields.get("name") or ""),
                "ms": int(fields.get("ms") or 0),
            }
            ok_raw = fields.get("ok")
            if isinstance(ok_raw, bool):
                rec["ok"] = ok_raw
            else:
                rec["ok"] = str(ok_raw).strip() in {"1", "true", "True"}
            action = str(fields.get("action") or "").strip()
            if action:
                rec["action"] = action
            self.tool_records.append(rec)
        gate = str(fields.get("gate") or "").strip()
        if gate:
            entry: dict[str, Any] = {"gate": gate, "at": event}
            action = str(fields.get("action") or "").strip()
            if action:
                entry["action"] = action
            self.gate_records.append(entry)
        if not self.enabled:
            return
        payload = {"t": self.elapsed_ms(), **fields}
        log.info(_format(event, payload, turn_id=self.id))

    def note_first_delta(self) -> None:
        if not self.enabled or self._first_delta_at is not None:
            return
        self._first_delta_at = time.perf_counter()
        # Agent-felt: first painted token, not Ollama prompt_eval_duration.
        self.mark("ttft", ms=self.elapsed_ms())

    def note_ollama_metrics(
        self,
        metrics: dict[str, Any] | None,
        *,
        round_n: int = 0,
    ) -> None:
        """Record one model round's engine prefill/decode stats (Ollama ns → ms)."""
        if not self.enabled or not isinstance(metrics, dict):
            return
        prefill_ms = ollama_ns_to_ms(metrics.get("prompt_eval_duration"))
        decode_ms = ollama_ns_to_ms(metrics.get("eval_duration"))
        prompt_n = metrics.get("prompt_eval_count")
        eval_n = metrics.get("eval_count")
        try:
            prompt_n_i = int(prompt_n) if prompt_n is not None else None
        except (TypeError, ValueError):
            prompt_n_i = None
        try:
            eval_n_i = int(eval_n) if eval_n is not None else None
        except (TypeError, ValueError):
            eval_n_i = None
        if prefill_ms is not None:
            self.model_prefill_ms += prefill_ms
        if decode_ms is not None:
            self.model_decode_ms += decode_ms
        if prompt_n_i is not None:
            self.last_prompt_eval_count = prompt_n_i
        if eval_n_i is not None:
            self.last_eval_count = eval_n_i
        fields: dict[str, Any] = {"round": int(round_n)}
        if prompt_n_i is not None:
            fields["prompt_eval_count"] = prompt_n_i
        if prefill_ms is not None:
            fields["prompt_eval_ms"] = prefill_ms
        if eval_n_i is not None:
            fields["eval_count"] = eval_n_i
        if decode_ms is not None:
            fields["eval_ms"] = decode_ms
        if len(fields) > 1:
            self.mark("ollama_metrics", **fields)

    def finish(self, status: str = "ok") -> str:
        """Write the summary line; return a short Thinking-dock blurb."""
        total = self.elapsed_ms()
        ttft = (
            int((self._first_delta_at - self._t0) * 1000)
            if self._first_delta_at is not None
            else -1
        )
        if self.enabled:
            done_fields: dict[str, Any] = {
                "status": status,
                "total_ms": total,
                "model_ms": self.model_ms,
                "summarize_ms": self.summarize_ms,
                "tool_ms": self.tool_ms,
                "confirm_ms": self.confirm_ms,
                "ttft_ms": ttft,
                "rounds": self.rounds,
                "tools": ",".join(self.tools) if self.tools else "-",
            }
            if self.model_prefill_ms:
                done_fields["model_prefill_ms"] = self.model_prefill_ms
            if self.model_decode_ms:
                done_fields["model_decode_ms"] = self.model_decode_ms
            actions = [
                str(r.get("action") or "")
                for r in self.tool_records
                if r.get("action")
            ]
            if actions:
                done_fields["actions"] = ",".join(actions)
            self.mark("done", **done_fields)
            _append_jsonl(self._jsonl_record(status, total, ttft))
        parts = [f"total={_sec(total)}", f"model={_sec(self.model_ms)}"]
        if self.model_prefill_ms:
            parts.append(f"prefill={_sec(self.model_prefill_ms)}")
        if self.model_decode_ms:
            parts.append(f"decode={_sec(self.model_decode_ms)}")
        if self.summarize_ms:
            parts.append(f"summarize={_sec(self.summarize_ms)}")
        if self.tool_ms:
            parts.append(f"tools={_sec(self.tool_ms)}")
        if self.confirm_ms:
            parts.append(f"confirm={_sec(self.confirm_ms)}")
        if ttft >= 0:
            parts.append(f"first_token={_sec(ttft)}")
        return "timing  " + " ".join(parts)

    def _jsonl_record(self, status: str, total: int, ttft: int) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": self.id,
            "session": self.session_id,
            "source": self.source,
            "role": self.role,
            "route_reason": self.route_reason,
            "status": status,
            "speak": self.speak,
            "user_chars": self.user_chars,
            "user_preview": self.user_preview,
            "total_ms": total,
            "model_ms": self.model_ms,
            "model_prefill_ms": self.model_prefill_ms,
            "model_decode_ms": self.model_decode_ms,
            "summarize_ms": self.summarize_ms,
            "tool_ms": self.tool_ms,
            "confirm_ms": self.confirm_ms,
            "ttft_ms": ttft,
            "rounds": self.rounds,
            "tools": list(self.tools),
            "tool_records": list(self.tool_records),
            "gates": list(self.gate_records),
            "stamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        }
        if self.history_kept is not None:
            record["history_kept"] = self.history_kept
        if self.history_dropped is not None:
            record["history_dropped"] = self.history_dropped
        if self.last_prompt_eval_count is not None:
            record["prompt_eval_count"] = self.last_prompt_eval_count
        if self.last_eval_count is not None:
            record["eval_count"] = self.last_eval_count
        return record


def _clip_preview(text: str, limit: int = 160) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _jsonl_path(log_dir: Path | None = None) -> Path:
    directory = log_dir or PROJECT_ROOT / "logs"
    return directory / "turns.jsonl"


def _append_jsonl(record: dict[str, Any]) -> None:
    path = _jsonl_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return


def _sec(ms: int) -> str:
    if ms < 0:
        return "?"
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def _format(event: str, fields: dict[str, Any], *, turn_id: str) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime())
    millis = int((time.time() % 1) * 1000)
    body = " ".join(f"{key}={_render(value)}" for key, value in fields.items())
    return f"turn {stamp}.{millis:03d} {event:<12} id={turn_id} {body}".rstrip()


def _render(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
