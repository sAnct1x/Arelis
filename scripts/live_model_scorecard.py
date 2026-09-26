"""Live multi-model scorecard at the production context window.

Hits Ollama on this machine. Writes incremental JSONL so a 27B crash can resume.
Default num_ctx is whatever load_config() pins (65536 on this card), not a
shrunk eval window.

    python scripts/live_model_scorecard.py
    python scripts/live_model_scorecard.py --models qwen3.5:9b
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from arelis.config import load_config
from arelis.paths import outputs_dir

GIB = 1024**3

MODELS = ("qwen3.5:9b", "qwen3.5:4b", "qwen3.5:27b")

SQL_PROMPT = """\
Derive the fundamental displacement sensitivity limit \
$\\tilde{x}_{\\mathrm{SQL}}(\\Omega)$ of a free-mass Fabry-Pérot-Michelson \
interferometer operating at the Standard Quantum Limit (SQL) under continuous \
position monitoring, and analyze its interplay with thermal noise. Perform \
all intermediate algebraic steps explicitly.

Formulate the single-sided displacement spectral densities of photon shot \
noise $S_x^{\\mathrm{shot}}(\\Omega)$ and quantum radiation-pressure noise \
$S_x^{\\mathrm{rad}}(\\Omega)$ as functions of circulating laser power $P$, \
laser angular frequency $\\omega_0$, arm length $L$, test mass $m$, and \
detection angular frequency $\\Omega$ (low-frequency limit below the cavity \
pole). Define $S_x^{\\mathrm{quantum}}(\\Omega)=S_x^{\\mathrm{shot}}+S_x^{\\mathrm{rad}}$. \
Minimize with respect to $P$ to obtain $P_{\\mathrm{opt}}(\\Omega)$ and the \
SQL $\\tilde{x}_{\\mathrm{SQL}}(\\Omega)=\\sqrt{S_x^{\\mathrm{quantum}}(P_{\\mathrm{opt}})}$.

Then write the Levin formula for coating Brownian thermal noise on a fused \
silica substrate at temperature $T=293\\,\\mathrm{K}$, $\\lambda=1064\\,\\mathrm{nm}$. \
Compare coating Brownian to the SQL in the 10–100 Hz band of a second-generation \
detector. State which term sets the mid-band floor and by roughly what factor.

Do not call weather, browser, or search. Use only algebra. If you use a \
calculator or python, say so. End with the simplified $\\tilde{x}_{\\mathrm{SQL}}$ \
after $P$ has been eliminated, and a one-row comparison at 100 Hz.\
"""

QUALITY: tuple[dict[str, Any], ...] = (
    {
        "id": "arith_17x19",
        "predict": 1024,
        "prompt": "What is 17 times 19? Reply with the integer only.",
    },
    {
        "id": "facts_trio",
        "predict": 1024,
        "prompt": (
            "Answer each on its own line, nothing else:\n"
            "1. What is the capital of Illinois?\n"
            "2. How many bits are in a byte?\n"
            "3. Is 1 a prime number?"
        ),
    },
    {
        "id": "hallu_cold_fusion",
        "predict": 1024,
        "prompt": (
            "Cite the 2019 Nature paper that proved cold fusion at MIT. "
            "Give the exact title, first author, and DOI."
        ),
    },
    {
        "id": "philosophy_gettier",
        "predict": 8192,
        "prompt": (
            "In 200–400 words: can Gettier cases be repaired by adding a "
            "no-false-lemmas condition? Take a position and address one "
            "objection. Do not invent citations, DOIs, or page numbers. "
            "If you name a paper, it must be a real well-known one and you "
            "must not fabricate a year or DOI."
        ),
    },
    {
        "id": "sql_ligo",
        "predict": 8192,
        "prompt": SQL_PROMPT,
    },
)

# Everyday surface, same names the product uses. Offered on every tool turn.
_TOOL_NAMES = (
    "calculator",
    "cas",
    "python",
    "weather",
    "send_sms",
    "inbound_sms",
    "agenda",
    "memory",
    "workspace",
    "recall",
    "web_search",
    "browser",
    "contacts",
    "tasks",
    "units",
)

CHOICE: tuple[dict[str, Any], ...] = (
    {"id": "choose_arith", "prompt": "what is 17 times 19?", "accepts": ("calculator",)},
    {
        "id": "choose_weather",
        "prompt": "what's the weather going to be like tomorrow?",
        "accepts": ("weather",),
    },
    {
        "id": "choose_sms",
        "prompt": "send a text to my wife telling her I love her",
        "accepts": ("send_sms",),
    },
    {
        "id": "choose_agenda",
        "prompt": "what's on my calendar today?",
        "accepts": ("agenda",),
    },
    {
        "id": "choose_memory",
        "prompt": "remember that I climb on Tuesdays",
        "accepts": ("memory",),
    },
    {
        "id": "choose_search",
        "prompt": "who won the F1 race this weekend?",
        "accepts": ("web_search",),
    },
    {
        "id": "choose_workspace",
        "prompt": "read arelis/core/tool_subset.py and tell me what it does",
        "accepts": ("workspace",),
    },
    {
        "id": "choose_browser",
        "prompt": "open youtube for me",
        "accepts": ("browser",),
    },
    {
        "id": "choose_not_weather",
        "prompt": (
            "Derive coating Brownian thermal noise on fused silica at "
            "temperature T = 293 K and wavelength 1064 nm. No weather."
        ),
        "accepts": ("cas", "python", "calculator", "units"),
        "forbid": ("weather",),
        "allow_none": True,
    },
)


def _short_tool(name: str) -> dict[str, Any]:
    from arelis.core.compact_prompt import skinny_description, skinny_ollama_tool

    schemas: dict[str, dict[str, Any]] = {
        "calculator": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
        "cas": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "expr": {"type": "string"},
            },
            "required": ["expr"],
        },
        "python": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
        "weather": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
        "send_sms": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "body"],
        },
        "inbound_sms": {"type": "object", "properties": {}},
        "agenda": {
            "type": "object",
            "properties": {"action": {"type": "string"}},
            "required": ["action"],
        },
        "memory": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "text": {"type": "string"},
            },
        },
        "workspace": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["action"],
        },
        "recall": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "web_search": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "browser": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["action"],
        },
        "contacts": {
            "type": "object",
            "properties": {"action": {"type": "string"}},
            "required": ["action"],
        },
        "tasks": {
            "type": "object",
            "properties": {"action": {"type": "string"}},
        },
        "units": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "quantity": {"type": "string"},
            },
        },
    }
    return skinny_ollama_tool(name, skinny_description(name, name), schemas.get(name))


def _http_json(base: str, path: str, payload: dict | None = None, timeout: float = 60) -> Any:
    url = f"{base}{path}"
    if payload is None:
        req = urllib.request.Request(url, method="GET")
    else:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def unload(base: str, model: str) -> None:
    try:
        _http_json(base, "/api/generate", {"model": model, "keep_alive": 0}, timeout=120)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass
    time.sleep(2.0)


def resident(base: str, model: str) -> dict[str, Any]:
    try:
        ps = _http_json(base, "/api/ps", timeout=30)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}
    row = next(
        (m for m in ps.get("models", []) if str(m.get("model", "")).startswith(model)),
        None,
    )
    if not row:
        return {}
    size = int(row.get("size") or 0)
    vram = int(row.get("size_vram") or 0)
    return {
        "size_gib": round(size / GIB, 2),
        "vram_gib": round(vram / GIB, 2),
        "fully_on_gpu": size > 0 and vram >= size,
        "context_length": row.get("context_length"),
        "processor": (row.get("details") or {}).get("family") or row.get("processor"),
    }


def chat(
    base: str,
    model: str,
    prompt: str,
    *,
    num_ctx: int,
    num_predict: int,
    tools: list[dict[str, Any]] | None = None,
    think: bool = True,
    timeout: float = 1800,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "think": think,
        "keep_alive": "10m",
        "options": {"num_ctx": num_ctx, "num_predict": num_predict},
    }
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    thinking: list[str] = []
    content: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    stats: dict[str, Any] = {}
    ttft: float | None = None
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message") or {}
                chunk_t = msg.get("thinking") or ""
                chunk_c = msg.get("content") or ""
                chunk_tools = msg.get("tool_calls") or []
                if ttft is None and (chunk_t or chunk_c or chunk_tools):
                    ttft = time.perf_counter() - t0
                if chunk_t:
                    thinking.append(chunk_t)
                if chunk_c:
                    content.append(chunk_c)
                if chunk_tools:
                    tool_calls.extend(chunk_tools)
                if obj.get("done"):
                    stats = {
                        "prompt_eval_count": obj.get("prompt_eval_count"),
                        "eval_count": obj.get("eval_count"),
                        "prompt_eval_duration_ns": obj.get("prompt_eval_duration"),
                        "eval_duration_ns": obj.get("eval_duration"),
                    }
        err = None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        err = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - t0
    text = "".join(content)
    thought = "".join(thinking)
    names: list[str] = []
    for call in tool_calls:
        fn = call.get("function") if isinstance(call, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            names.append(str(fn["name"]))
        elif isinstance(call, dict) and call.get("name"):
            names.append(str(call["name"]))
    prompt_tok = stats.get("prompt_eval_count")
    out_tok = stats.get("eval_count")
    eval_ns = stats.get("eval_duration_ns") or 0
    toks_s = (float(out_tok) / (eval_ns / 1e9)) if out_tok and eval_ns else None
    return {
        "text": text,
        "thinking": thought,
        "tool_names": names,
        "tool_calls": tool_calls,
        "ttft_s": None if ttft is None else round(ttft, 3),
        "wall_s": round(wall, 3),
        "prompt_tokens": prompt_tok,
        "out_tokens": out_tok,
        "toks_s": None if toks_s is None else round(toks_s, 2),
        "error": err,
        "resident": resident(base, model),
    }


def _has(text: str, *needles: str) -> bool:
    blob = text.lower()
    return all(n.lower() in blob for n in needles)


def grade_arith(row: dict[str, Any]) -> dict[str, Any]:
    text = row.get("text") or ""
    ok = bool(re.search(r"\b323\b", text))
    return {"ok": ok, "notes": [] if ok else ["missing 323"]}


def grade_facts(row: dict[str, Any]) -> dict[str, Any]:
    text = row.get("text") or ""
    notes: list[str] = []
    if not re.search(r"columbus", text, re.I):
        notes.append("capital not Columbus")
    if not re.search(r"\b8\b", text):
        notes.append("bits-in-byte not 8")
    if re.search(r"\byes\b", text, re.I) and re.search(r"prime", text, re.I):
        # "Yes" on line 3 is the failure; "No" is the pass.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        prime_line = next((ln for ln in lines if re.search(r"prime|1", ln, re.I)), "")
        if re.search(r"\byes\b", prime_line, re.I) and not re.search(
            r"\bno\b", prime_line, re.I
        ):
            notes.append("called 1 prime")
    elif not re.search(r"\bno\b", text, re.I):
        notes.append("did not say 1 is not prime")
    return {"ok": not notes, "notes": notes}


def grade_hallu(row: dict[str, Any]) -> dict[str, Any]:
    text = row.get("text") or ""
    blob = text.lower()
    invented = bool(re.search(r"10\.\d{4,}/", text)) or bool(
        re.search(r"arxiv\.org|doi\.org", blob)
    )
    denies = bool(
        re.search(
            r"\b(no such|does not exist|never (published|proved)|not (a |an )?(real|actual)|"
            r"there (is|was) no|i (can't|cannot) cite|no 2019)\b",
            blob,
        )
    )
    claims = bool(
        re.search(r"\b(proved|demonstrated|published in nature|the paper is)\b", blob)
    )
    ok = denies and not (invented and claims)
    notes: list[str] = []
    if invented:
        notes.append("invented DOI/arxiv")
    if claims and not denies:
        notes.append("treated the fake paper as real")
    if not denies:
        notes.append("did not reject the premise")
    return {"ok": ok, "notes": notes}


def grade_philosophy(row: dict[str, Any]) -> dict[str, Any]:
    text = row.get("text") or ""
    words = len(re.findall(r"[A-Za-z']+", text))
    notes: list[str] = []
    if words < 80:
        notes.append(f"too short ({words} words)")
    if re.search(r"10\.\d{4,}/", text):
        notes.append("fabricated-looking DOI")
    if re.search(r"arxiv:\s*\d", text, re.I):
        notes.append("arxiv id")
    if not re.search(r"gettier|lemma|justif|false", text, re.I):
        notes.append("never engaged Gettier / lemmas")
    if not re.search(
        r"\b(cannot|can|does not|fails|insufficient|not enough|still|"
        r"objection|however|but)\b",
        text,
        re.I,
    ):
        notes.append("no position or objection")
    return {"ok": not notes, "notes": notes, "words": words}


def grade_sql(row: dict[str, Any]) -> dict[str, Any]:
    visible = (row.get("text") or "").strip()
    text = visible + "\n" + (row.get("thinking") or "")
    blob = text.lower()
    notes: list[str] = []
    if not visible:
        notes.append("empty chat (thinking only)")
    if "weather" in (row.get("tool_names") or []):
        notes.append("called weather")
    # After P_opt the SQL of a free mass is ~sqrt(hbar / (m Omega^2)), not a
    # leftover function of P, L, omega_0.
    keeps_power = bool(
        re.search(
            r"x[_\s\\]*\{?\\?mathrm\{?sql\}?\}?[^\n]{0,80}(P_|P\b|omega_0|\\omega_0)",
            text,
        )
    ) and not re.search(r"independent of (?:power|p\b)|eliminat(?:e|ed) p", blob)
    if keeps_power and re.search(r"p_?\{?\\?mathrm\{?opt", blob):
        notes.append("SQL after P_opt still carries P / L / ω0")
    if re.search(r"0\.0[5-9]\s*\\?times\s*10\^\{?-?21", text) or re.search(
        r"coating[^\n]{0,40}0\.0[5-9]", blob
    ):
        notes.append("coating Brownian ~0.08e-21 (too low; hierarchy backwards)")
    if re.search(r"quantum (wins|dominates|below coating)", blob) and re.search(
        r"10\s*[–-]\s*100\s*hz", blob
    ):
        notes.append("quantum winning 10–100 Hz (coating should floor)")
    if not re.search(r"\\hbar|hbar|ℏ", text):
        notes.append("no ħ in the write-up")
    if not re.search(r"coating", blob):
        notes.append("no coating Brownian")
    # Shot-noise-as-seconds-squared is the 9B failure mode.
    if re.search(r"s\^2(?!\s*/)|units check[^\n]{0,40}s", blob) and not re.search(
        r"m\^2\s*/\s*hz|m²/hz", blob
    ):
        notes.append("shot-noise units look like s², not m²/Hz")
    if not visible:
        return {"ok": False, "notes": notes}
    return {"ok": len(notes) <= 1, "notes": notes}


GRADERS = {
    "arith_17x19": grade_arith,
    "facts_trio": grade_facts,
    "hallu_cold_fusion": grade_hallu,
    "philosophy_gettier": grade_philosophy,
    "sql_ligo": grade_sql,
}


def grade_choice(spec: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    names = list(row.get("tool_names") or [])
    first = names[0] if names else ""
    forbid = tuple(spec.get("forbid") or ())
    if first and first in forbid:
        return {"ok": False, "notes": [f"called forbidden {first}"], "picked": first}
    if first in spec["accepts"]:
        return {"ok": True, "notes": [], "picked": first}
    if not first and spec.get("allow_none"):
        return {"ok": True, "notes": ["answered in prose (allowed)"], "picked": ""}
    return {
        "ok": False,
        "notes": [f"called {first or 'nothing'}, wanted {', '.join(spec['accepts'])}"],
        "picked": first,
    }


def _load_done(path: Path) -> set[tuple[str, str, str]]:
    done: set[tuple[str, str, str]] = set()
    if not path.is_file():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (row.get("model"), row.get("track"), row.get("id"))
        if all(key) and not row.get("error"):
            done.add(key)  # type: ignore[arg-type]
    return done


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def _clip(text: str, n: int = 4000) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def run_one(
    base: str,
    model: str,
    num_ctx: int,
    spec: dict[str, Any],
    track: str,
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    predict = int(spec.get("predict") or (768 if track == "choice" else 1024))
    raw = chat(
        base,
        model,
        spec["prompt"],
        num_ctx=num_ctx,
        num_predict=predict,
        tools=tools,
        think=True,
    )
    if track == "quality":
        grade = GRADERS[spec["id"]](raw)
    else:
        grade = grade_choice(spec, raw)
    row = {
        "model": model,
        "track": track,
        "id": spec["id"],
        "num_ctx": num_ctx,
        "ok": grade.get("ok"),
        "notes": grade.get("notes"),
        "picked": grade.get("picked"),
        "words": grade.get("words"),
        "ttft_s": raw["ttft_s"],
        "wall_s": raw["wall_s"],
        "prompt_tokens": raw["prompt_tokens"],
        "out_tokens": raw["out_tokens"],
        "toks_s": raw["toks_s"],
        "tool_names": raw["tool_names"],
        "text": _clip(raw["text"], 8000),
        "thinking": _clip(raw["thinking"], 4000),
        "error": raw["error"],
        "resident": raw["resident"],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # Thinking can consume the whole budget; empty chat is not a scored miss.
    if (
        not row["error"]
        and not (raw.get("text") or "").strip()
        and not raw.get("tool_names")
        and raw.get("out_tokens")
        and int(raw["out_tokens"]) >= predict
    ):
        row["error"] = "truncated_thinking"
        row["ok"] = False
        row["notes"] = [*(row.get("notes") or []), "thinking ate num_predict"]
    return row


def _norm_tag(tag: str) -> str:
    t = (tag or "").strip().lower()
    if t.endswith(":latest"):
        t = t[: -len(":latest")]
    return t


def listed_tags() -> list[str]:
    import subprocess

    proc = subprocess.run(
        ["ollama", "list"], capture_output=True, text=True, check=False
    )
    tags: list[str] = []
    for line in (proc.stdout or "").splitlines():
        name = line.split()[0] if line.split() else ""
        if not name or name.lower() == "name":
            continue
        tags.append(name)
    return tags


def keep_tags(cfg: dict[str, Any]) -> set[str]:
    """Pinned product tags. Eval guests are not in this set."""
    models = cfg.get("models") or {}
    memory = cfg.get("memory") or {}
    raw = [
        models.get("fast"),
        models.get("research"),
        models.get("vision"),
        memory.get("embed_model"),
        "nomic-embed-text",
        "qwen2.5vl:3b",
        "qwen3.5:9b",
    ]
    return {_norm_tag(str(t)) for t in raw if t}


def ensure_tag(tag: str) -> bool:
    import subprocess

    have = {_norm_tag(t) for t in listed_tags()}
    if _norm_tag(tag) in have:
        print(f"have {tag}", flush=True)
        return True
    print(f"pull {tag} …", flush=True)
    proc = subprocess.run(["ollama", "pull", tag], check=False)
    if proc.returncode != 0:
        print(f"PULL FAILED {tag} exit={proc.returncode}", flush=True)
        return False
    return True


def drop_tag(base: str, tag: str) -> None:
    import subprocess

    unload(base, tag)
    print(f"rm {tag}", flush=True)
    proc = subprocess.run(["ollama", "rm", tag], check=False)
    if proc.returncode != 0:
        print(f"RM FAILED {tag} exit={proc.returncode}", flush=True)


def scrub_unused(base: str, keep: set[str]) -> None:
    """Delete every local tag that is not a product pin.

    4B / 27B and any leftover old chat weights go. Daily driver, vision
    fallback, and the embed model stay.
    """
    leftover = [t for t in listed_tags() if _norm_tag(t) not in keep]
    if not leftover:
        print(f"disk: only product tags remain ({', '.join(sorted(keep))})", flush=True)
        return
    print(f"scrub unused: {', '.join(leftover)}", flush=True)
    for tag in leftover:
        drop_tag(base, tag)
    still = [t for t in listed_tags() if _norm_tag(t) not in keep]
    print(f"left: {', '.join(listed_tags()) or '(none)'}", flush=True)
    if still:
        print(f"still unused after scrub: {', '.join(still)}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:11434")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--skip-pull", action="store_true")
    ap.add_argument("--keep-eval-models", action="store_true")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    cfg = load_config()
    num_ctx = int(((cfg.get("ollama") or {}).get("num_ctx")) or 65536)
    keep = keep_tags(cfg)
    out = outputs_dir() / "live_model_scorecard" / "runs.jsonl"
    done = _load_done(out)
    lock = out.with_suffix(".lock")
    if lock.is_file():
        try:
            old = int(lock.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            old = 0
        if old and old != os.getpid():
            try:
                os.kill(old, 0)
            except OSError:
                pass
            else:
                print(f"another scorecard is pid {old}; refusing to start", flush=True)
                return 2
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    print(f"num_ctx={num_ctx}  out={out}  resume={len(done)}", flush=True)
    print(f"keep {sorted(keep)}", flush=True)

    tools = [_short_tool(n) for n in _TOOL_NAMES]
    try:
        for model in models:
            print(f"\n=== {model} ===", flush=True)
            if not args.skip_pull and not ensure_tag(model):
                print(f"skip model {model}: not on disk", flush=True)
                continue
            # Pin the production window before the first scored turn.
            try:
                chat(
                    args.base,
                    model,
                    "Reply with the single word: ok",
                    num_ctx=num_ctx,
                    num_predict=8,
                    think=False,
                    timeout=600,
                )
            except Exception as exc:
                print(f"warmup failed: {exc}", flush=True)
            print(f"resident {resident(args.base, model)}", flush=True)
            for spec in QUALITY:
                key = (model, "quality", spec["id"])
                if key in done:
                    print(f"skip {key}", flush=True)
                    continue
                row = run_one(args.base, model, num_ctx, spec, "quality", None)
                _append(out, row)
                print(
                    f"{'PASS' if row['ok'] else 'FAIL':4}  quality {spec['id']:<22}  "
                    f"ttft={row['ttft_s']}s wall={row['wall_s']}s  "
                    f"{'; '.join(row['notes'] or []) or row.get('error') or ''}",
                    flush=True,
                )
            for spec in CHOICE:
                key = (model, "choice", spec["id"])
                if key in done:
                    print(f"skip {key}", flush=True)
                    continue
                row = run_one(args.base, model, num_ctx, spec, "choice", tools)
                _append(out, row)
                print(
                    f"{'PASS' if row['ok'] else 'FAIL':4}  choice  {spec['id']:<22}  "
                    f"picked={row.get('picked') or '—'}  "
                    f"ttft={row['ttft_s']}s wall={row['wall_s']}s  "
                    f"{'; '.join(row['notes'] or []) or ''}",
                    flush=True,
                )
            unload(args.base, model)
            if not args.keep_eval_models and _norm_tag(model) not in keep:
                drop_tag(args.base, model)
    finally:
        if not args.keep_eval_models:
            scrub_unused(args.base, keep)
        try:
            lock.unlink()
        except OSError:
            pass
    print(f"\nwrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
