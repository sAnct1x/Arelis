"""Keep the persona inside the context window.

Ollama silently drops overflow from the front of the prompt. The agent loop
puts system messages first, so a long session loses the persona and tool policy
before it loses stale chat. Fitting here, with those messages pinned, is what
stops that.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from arelis.paths import state_dir

log = logging.getLogger(__name__)

# Seed until a real prompt_eval_count arrives. Roughly right for English prose
# on the Qwen family; calibration replaces it per model after a few turns.
DEFAULT_CHARS_PER_TOKEN = 4.0

# Room for the reply. Without this, a prompt that fills num_ctx leaves the
# model nowhere to write, and Ollama still truncates the front to make space.
_REPLY_RESERVE_TOKENS = 1024

_DEFAULT_RATIOS_PATH = state_dir() / "token_ratios.json"


def estimate_tokens(text: str, *, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> int:
    """Approximate token count from character length.

    Exact counts need a model-specific tokenizer we do not ship. The ratio is
    seeded at 4.0 and corrected from Ollama's prompt_eval_count when a stream
    finishes, so the estimate tightens without a second model.
    """
    if not text:
        return 0
    ratio = chars_per_token if chars_per_token > 0 else DEFAULT_CHARS_PER_TOKEN
    return max(1, int(len(text) / ratio))


def message_tokens(
    message: dict[str, Any], *, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN
) -> int:
    content = message.get("content") or ""
    if not isinstance(content, str):
        content = str(content)
    return estimate_tokens(content, chars_per_token=chars_per_token)


def context_budget(
    num_ctx: int,
    *,
    tool_output_chars: int,
    reply_reserve_tokens: int = _REPLY_RESERVE_TOKENS,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
    schema_chars: int = 0,
) -> int:
    """Tokens available for pinned system messages plus chat history.

    Reserves space for one full tool result and for the reply. Mid-turn tool
    rounds append into that reserve; without it, the first scrape would push
    the persona off the front of the window again.

    ``schema_chars`` is the serialised tool array. It is prompt like any other,
    and leaving it out meant the budget handed history room the schemas had
    already spent — on a full registry that is thousands of tokens, so the
    window overflowed at the front, which is the persona.
    """
    tool_reserve = estimate_tokens("x" * max(0, tool_output_chars), chars_per_token=chars_per_token)
    schema_reserve = estimate_tokens(
        "x" * max(0, int(schema_chars)), chars_per_token=chars_per_token
    )
    return max(
        0,
        int(num_ctx) - int(reply_reserve_tokens) - tool_reserve - schema_reserve,
    )


def allocate_history(
    history: list[dict[str, Any]],
    token_budget: int,
    *,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split history into (kept newest, dropped oldest) under a token budget.

    The newest message is kept even when it alone exceeds the budget, so the
    user turn that triggered the request is never the thing discarded.
    """
    if not history or token_budget <= 0:
        # Budget already spent on pinned content: everything is dropped except
        # we still keep the newest message so the model sees the ask.
        if not history:
            return [], []
        return [history[-1]], list(history[:-1])

    kept: list[dict[str, Any]] = []
    used = 0
    for message in reversed(history):
        cost = message_tokens(message, chars_per_token=chars_per_token)
        if used + cost > token_budget:
            if not kept:
                kept.append(message)
            break
        kept.append(message)
        used += cost
    kept.reverse()
    dropped = history[: len(history) - len(kept)]
    return kept, dropped


def split_recent_history(
    history: list[dict[str, Any]],
    min_recent: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split into (older, tail). Tail is the last min_recent messages.

    The tail is the live conversation: prior turns plus the current user
    line. Pin it so a fat system prefix cannot drop turn N before turn N+1
    is answered. ``min_recent`` is at least 1 so the current ask survives.
    """
    keep = max(1, int(min_recent))
    if not history:
        return [], []
    if len(history) <= keep:
        return [], list(history)
    return list(history[:-keep]), list(history[-keep:])


def fit_messages(
    pinned: list[dict[str, Any]],
    history: list[dict[str, Any]],
    budget: int,
    *,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> list[dict[str, Any]]:
    """Return pinned messages plus the newest history that fits under budget.

    Pinned messages are never dropped, even when they alone exceed the budget.
    That is deliberate: a truncated persona is worse than a short reply, and the
    whole point of this function is that system content must survive.
    """
    pinned_cost = sum(message_tokens(m, chars_per_token=chars_per_token) for m in pinned)
    remaining = budget - pinned_cost
    if remaining <= 0:
        kept, _dropped = allocate_history(history, 0, chars_per_token=chars_per_token)
        return [*pinned, *kept]
    kept, _dropped = allocate_history(history, remaining, chars_per_token=chars_per_token)
    return [*pinned, *kept]


def prompt_char_count(
    messages: list[dict[str, Any]], *, tools: Any = None
) -> int:
    """Sum of message contents, used to derive chars-per-token from eval counts.

    Pass the same ``tools`` array that went to the model. Ollama counts the tool
    schemas in prompt_eval_count, so leaving them out of the numerator was not
    the small conservative error the old comment claimed: on a tool-bearing turn
    the schemas are most of the prompt, and dividing a fraction of the characters
    by all of the tokens learned a ratio near 2.3 where Qwen prose is nearer 4.5.
    Everything then looked about twice as expensive as it was, so history was
    dropped that would have fit.

    Role framing and the chat template are still uncounted, which does leave the
    estimate slightly conservative — in the safe direction.
    """
    total = 0
    for message in messages:
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        total += len(content)
    if tools:
        try:
            total += len(json.dumps(tools))
        except (TypeError, ValueError):
            pass
    return total


class TokenRatios:
    """Per-model chars-per-token ratios learned from Ollama's prompt_eval_count."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else _DEFAULT_RATIOS_PATH
        self._ratios: dict[str, float] = {}
        self._load()

    def get(self, model: str) -> float:
        return self._ratios.get(model, DEFAULT_CHARS_PER_TOKEN)

    def observe(self, model: str, prompt_chars: int, prompt_eval_count: int) -> float | None:
        """Update the stored ratio for model. Returns the new ratio, or None if unusable."""
        if not model or prompt_chars <= 0 or prompt_eval_count <= 0:
            return None
        observed = prompt_chars / float(prompt_eval_count)
        # Reject ratios that are clearly not about this tokenizer. A bad chunk
        # should not yank the estimate to something that fits nothing, or that
        # never trims.
        if observed < 1.0 or observed > 16.0:
            log.info(
                "Ignoring implausible token ratio %.2f for %s (%d chars / %d tokens)",
                observed,
                model,
                prompt_chars,
                prompt_eval_count,
            )
            return None
        previous = self._ratios.get(model)
        if previous is None:
            updated = observed
        else:
            # Half-life of a couple of turns so one outlier does not stick.
            updated = 0.5 * previous + 0.5 * observed
        self._ratios[model] = updated
        self._save()
        return updated

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        for key, value in raw.items():
            try:
                ratio = float(value)
            except (TypeError, ValueError):
                continue
            if 1.0 <= ratio <= 16.0:
                self._ratios[str(key)] = ratio

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._ratios, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("Could not write token ratios to %s: %s", self.path, exc)
