"""Per-turn ranked memory retrieval for the chat prompt.

Active facts used to be pinned unranked (up to 24 / 1200 characters) in the
cached prefix, and preferences and decisions were never injected. This module
picks a small set of memories that score above a relevance threshold for the
current ask, so unrelated rows stay out of the prompt.

Ranking combines embedding cosine similarity (when the CPU embedder is already
up), keyword overlap, and recency. The injected block is bounded: at most
``MAX_ITEMS`` rows and ``MAX_PROMPT_CHARS`` characters, including the header.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from arelis.memory.indexer import DEFAULT_EMBED_MODEL
from arelis.memory.store import MemoryStore

log = logging.getLogger(__name__)

# Prompt bound. Stated here and in docs/memory.md.
MAX_ITEMS = 6
MAX_PROMPT_CHARS = 800
MAX_ITEM_CHARS = 160

# Candidate pool loaded from the store before scoring.
_MAX_FACTS = 100
_MAX_PREFERENCES = 100
_MAX_DECISIONS = 100
# Skip a mid-turn embed batch when the pool is larger than this.
_EMBED_BATCH_CAP = 80
# Bound the mid-turn embed so a hung CPU embedder cannot inherit the
# 300s chat HTTP timeout. A timeout falls back to keyword plus recency.
_EMBED_TIMEOUT_S = 2.0

# Combined score = weighted sum in [0, 1]. Recency alone cannot pass.
EMBED_WEIGHT = 0.55
KEYWORD_WEIGHT = 0.30
RECENCY_WEIGHT = 0.15
KEYWORD_WEIGHT_NO_EMBED = 0.80
RECENCY_WEIGHT_NO_EMBED = 0.20
# With embeddings, a paraphrase can pass on cosine alone if it is strong.
RELEVANCE_THRESHOLD = 0.28
# Without embeddings, recency-only tops out at 0.20, so a keyword hit is required.
RELEVANCE_THRESHOLD_NO_EMBED = 0.34
RECENCY_HALF_LIFE_DAYS = 30.0

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "am",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "it",
        "they",
        "to",
        "of",
        "in",
        "on",
        "for",
        "and",
        "or",
        "but",
        "with",
        "about",
        "what",
        "which",
        "who",
        "whom",
        "when",
        "where",
        "why",
        "how",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "can",
        "could",
        "would",
        "should",
        "will",
        "this",
        "that",
        "these",
        "those",
        "please",
        "tell",
        "know",
        "remember",
        "something",
        "anything",
    }
)

_TOKEN = re.compile(r"[a-z0-9]+")
_QUESTION_WORDS = ("what", "which", "who", "whom", "whose", "where", "when", "why", "how")
# A new question starts after "?" or at ", and what ..." / "also how ...".
# Sentence ends and "!" are not breaks: "Ok. <long ask>" is one ask.
_SUBQUESTION_SPLIT = re.compile(
    r"\?+|,?\s+(?:and|also)\s+(?=(?:" + "|".join(_QUESTION_WORDS) + r")\b)",
    re.IGNORECASE,
)
# A sub-question scores alone only if it opens with a question word or has
# this many content words, so "Ok?" or "Thanks?" cannot match on one word.
_MIN_PART_WORDS = 3
_MAX_PARTS = 4

EmbedFn = Callable[[str, list[str]], Awaitable[list[list[float]]]]
ModelCheckFn = Callable[[], Awaitable[bool]]


@dataclass(slots=True)
class MemoryItem:
    """One durable row that can be considered for this turn."""

    item_id: str
    kind: str
    text: str
    updated_at: str
    embedding: list[float] | np.ndarray | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ScoredMemory:
    item: MemoryItem
    score: float
    keyword: float
    recency: float
    embedding: float


def tokenize_for_match(text: str) -> set[str]:
    """Content tokens used for keyword overlap. Stopwords are dropped."""
    tokens = _TOKEN.findall(text.lower())
    return {token for token in tokens if token not in _STOPWORDS and len(token) >= 2}


# Tokens that must match exactly. Stemming "window" to "windows" would
# treat an OS decision as a hit for a question about a window layout.
_NO_STEM = frozenset({"window", "windows"})


def _token_variants(token: str) -> set[str]:
    """Light stems so 'replies' meets 'reply' and 'usually' meets 'usual'."""
    if token in _NO_STEM:
        return {token}
    variants = {token}
    if len(token) > 4 and token.endswith("ly"):
        variants.add(token[:-2])
    if len(token) > 4 and token.endswith("ies"):
        variants.add(token[:-3] + "y")
    if len(token) > 4 and token.endswith("es"):
        variants.add(token[:-2])
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        variants.add(token[:-1])
    return variants


_QueryPart = list[set[str]]


def _query_parts(query: str) -> list[_QueryPart]:
    """The whole ask, then up to ``_MAX_PARTS`` sub-questions, as stem sets.

    A compound ask ("how long are my exposures, and what finder do I have?")
    is scored per sub-question, as if each were asked alone, so the words of
    one part do not dilute a fact that answers the other part.
    """
    token_sets = [tokenize_for_match(query)]
    pieces = _SUBQUESTION_SPLIT.split(query)
    if len(pieces) > 1:
        for piece in pieces:
            tokens = tokenize_for_match(piece)
            if not tokens:
                continue
            words = _TOKEN.findall(piece.lower())
            if len(tokens) < _MIN_PART_WORDS and words[0] not in _QUESTION_WORDS:
                continue
            token_sets.append(tokens)
            if len(token_sets) > _MAX_PARTS:
                break
    return [
        [_token_variants(token) for token in tokens] for tokens in token_sets if tokens
    ]


def _keyword_score_parts(parts: list[_QueryPart], text: str) -> float:
    """Best fraction of one part's content tokens found in the text."""
    text_tokens = tokenize_for_match(text)
    if not text_tokens:
        return 0.0
    text_variants: set[str] = set()
    for token in text_tokens:
        text_variants.update(_token_variants(token))
    best = 0.0
    for part in parts:
        hits = sum(1 for variants in part if variants & text_variants)
        best = max(best, hits / len(part))
    return best


def keyword_score(query: str, text: str) -> float:
    """Best fraction of the ask's (or one sub-question's) tokens in the text."""
    return _keyword_score_parts(_query_parts(query), text)


def recency_score(
    updated_at: str,
    *,
    now: datetime | None = None,
    half_life_days: float = RECENCY_HALF_LIFE_DAYS,
) -> float:
    """Exponential decay from 1 (just updated) toward 0. Missing dates score 0."""
    if not updated_at:
        return 0.0
    try:
        stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    age_days = max(0.0, (moment - stamp).total_seconds() / 86400.0)
    life = half_life_days if half_life_days > 0 else RECENCY_HALF_LIFE_DAYS
    return float(0.5 ** (age_days / life))


def embedding_score(
    query_embedding: list[float] | np.ndarray | None,
    item_embedding: list[float] | np.ndarray | None,
) -> float:
    """Cosine similarity in [0, 1]. Zero when either vector is missing."""
    if query_embedding is None or item_embedding is None:
        return 0.0
    query = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
    item = np.asarray(item_embedding, dtype=np.float32).reshape(-1)
    if query.size == 0 or item.size == 0 or query.size != item.size:
        return 0.0
    query_norm = float(np.linalg.norm(query))
    item_norm = float(np.linalg.norm(item))
    if query_norm == 0.0 or item_norm == 0.0:
        return 0.0
    cosine = float(np.dot(query, item) / (query_norm * item_norm))
    return max(0.0, min(1.0, cosine))


def combined_score(
    *,
    keyword: float,
    recency: float,
    embedding: float,
    has_embeddings: bool,
) -> float:
    if has_embeddings:
        return (
            EMBED_WEIGHT * embedding
            + KEYWORD_WEIGHT * keyword
            + RECENCY_WEIGHT * recency
        )
    return KEYWORD_WEIGHT_NO_EMBED * keyword + RECENCY_WEIGHT_NO_EMBED * recency


def collect_memory_items(store: MemoryStore) -> list[MemoryItem]:
    """Load active facts, preferences, and decisions as retrieval candidates.

    Pending, rejected, and forgotten facts are never candidates.
    """
    items: list[MemoryItem] = []
    for row in store.list_facts(status="active", limit=_MAX_FACTS):
        text = " ".join(str(row.get("text") or "").split())
        if not text:
            continue
        items.append(
            MemoryItem(
                item_id=f"fact:{int(row['id'])}",
                kind="fact",
                text=text,
                updated_at=str(row.get("updated_at") or ""),
            )
        )
    for row in store.list_preferences(limit=_MAX_PREFERENCES):
        key = " ".join(str(row.get("key") or "").split())
        value = " ".join(str(row.get("value") or "").split())
        if not key or not value:
            continue
        items.append(
            MemoryItem(
                item_id=f"preference:{int(row['id'])}",
                kind="preference",
                text=f"{key}: {value}",
                updated_at=str(row.get("updated_at") or ""),
            )
        )
    for row in store.list_all_decisions(limit=_MAX_DECISIONS):
        project = " ".join(str(row.get("project") or "").split())
        text = " ".join(str(row.get("text") or "").split())
        if not text:
            continue
        label = f"{project}: {text}" if project else text
        items.append(
            MemoryItem(
                item_id=f"decision:{int(row['id'])}",
                kind="decision",
                text=label,
                updated_at=str(row.get("updated_at") or ""),
            )
        )
    return items


def score_items(
    query: str,
    items: list[MemoryItem],
    *,
    query_embedding: list[float] | np.ndarray | None = None,
    now: datetime | None = None,
) -> list[ScoredMemory]:
    """Score every candidate. Embeddings contribute only when the query has one."""
    has_embeddings = query_embedding is not None
    scored: list[ScoredMemory] = []
    parts = _query_parts(query)
    for item in items:
        keyword = _keyword_score_parts(parts, item.text)
        recency = recency_score(item.updated_at, now=now)
        embed = embedding_score(query_embedding, item.embedding)
        scored.append(
            ScoredMemory(
                item=item,
                score=combined_score(
                    keyword=keyword,
                    recency=recency,
                    embedding=embed,
                    has_embeddings=has_embeddings,
                ),
                keyword=keyword,
                recency=recency,
                embedding=embed,
            )
        )
    scored.sort(key=lambda row: row.score, reverse=True)
    return scored


def select_relevant(
    scored: list[ScoredMemory],
    *,
    has_embeddings: bool,
    limit: int = MAX_ITEMS,
) -> list[MemoryItem]:
    """Keep items at or above the threshold, then apply the count cap.

    Near-duplicate rows of one fact take a single slot (the best-scored one).
    """
    threshold = RELEVANCE_THRESHOLD if has_embeddings else RELEVANCE_THRESHOLD_NO_EMBED
    cap = max(0, min(int(limit), MAX_ITEMS))
    picked: list[MemoryItem] = []
    picked_keys: list[_DuplicateKey] = []
    for row in scored:
        if row.score < threshold:
            continue
        if not has_embeddings and row.keyword <= 0.0:
            continue
        key = _duplicate_key(row.item.text)
        if any(_near_duplicate(key, seen) for seen in picked_keys):
            continue
        picked.append(row.item)
        picked_keys.append(key)
        if len(picked) >= cap:
            break
    return picked


_NUMBER_WORDS = frozenset(
    {
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
        "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
        "thousand", "million", "half", "dozen",
    }
)
_POSSESSIVE = re.compile(r"\b([a-z]+)'s\b")
# "user's" is the owner; the rest are contractions, not possessives.
_NOT_OTHER_OWNER = frozenset(
    {"user", "it", "that", "there", "here", "what", "who", "where", "he", "she", "let"}
)
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'"})
_THE_USER = re.compile(r"\bthe\s+user(?:'s)?\b")
# Words that only say whose fact it is, and filler. Unlike _STOPWORDS,
# "should", "will" and "not" stay: they change what the fact says.
_DUPLICATE_SKIP = frozenset(
    {"i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "you", "your",
     "yours", "a", "an", "the", "is", "are", "am", "be", "of", "on", "in", "at",
     "to", "for", "with", "and", "that", "this", "it", "s"}
)
# "can't", "cant" and "cannot" are one negation, so each spelling says "not".
_NEGATION_FORMS = {
    "cannot": ("can", "not"), "cant": ("can", "not"), "wont": ("will", "not"),
    "dont": ("do", "not"), "doesnt": ("does", "not"), "didnt": ("did", "not"),
    "isnt": ("is", "not"), "arent": ("are", "not"), "wasnt": ("was", "not"),
    "werent": ("were", "not"), "hasnt": ("has", "not"), "havent": ("have", "not"),
    "shouldnt": ("should", "not"), "couldnt": ("could", "not"),
    "wouldnt": ("would", "not"),
}


@dataclass(frozen=True, slots=True)
class _DuplicateKey:
    words: tuple[str, ...]
    numbers: frozenset[str]
    possessives: frozenset[str]


def _duplicate_key(text: str) -> _DuplicateKey:
    lowered = text.lower().translate(_APOSTROPHES)
    raw = re.sub(r"n't\b", "nt", _THE_USER.sub(" ", lowered))
    words: list[str] = []
    for token in _TOKEN.findall(raw):
        for part in _NEGATION_FORMS.get(token, (token,)):
            if part in _DUPLICATE_SKIP:
                continue
            if len(part) > 3 and part.endswith("s") and not part.endswith("ss"):
                part = part[:-1]
            words.append(part)
    return _DuplicateKey(
        words=tuple(words),
        numbers=frozenset(
            token
            for token in _TOKEN.findall(lowered)
            if any(char.isdigit() for char in token) or token in _NUMBER_WORDS
        ),
        possessives=frozenset(
            name
            for name in _POSSESSIVE.findall(lowered)
            if name not in _NOT_OTHER_OWNER
        ),
    )


def _near_duplicate(left: _DuplicateKey, right: _DuplicateKey) -> bool:
    """Same fact reworded: the same content words in the same order, once
    owner words ("my", "the user's"), filler, punctuation, hyphens, plurals
    and "dont" vs "don't" are set aside, and no change of number or of
    whose thing it is ("sister's"). Any added, swapped or reordered word
    (least, should, not, Boston to Denver vs Denver to Boston) keeps both."""
    return (
        bool(left.words)
        and left.words == right.words
        and left.numbers == right.numbers
        and left.possessives == right.possessives
    )


def _clip_item_text(text: str) -> str:
    """Fit one memory into the per-item cap, breaking on a word boundary."""
    if len(text) <= MAX_ITEM_CHARS:
        return text
    budget = MAX_ITEM_CHARS - 1
    clipped = text[:budget]
    if budget < len(text) and not text[budget].isspace():
        end = len(clipped)
        while end > 0 and not clipped[end - 1].isspace():
            end -= 1
        clipped = clipped[:end]
    clipped = clipped.rstrip()
    if not clipped:
        clipped = text[:budget].rstrip()
    return clipped + "…"


def format_retrieval_block(items: list[MemoryItem]) -> str:
    """Compact system block, or empty when nothing relevant survived the cap."""
    if not items:
        return ""
    lines = [
        "Relevant memories for this turn (ranked for the current ask; "
        "treat as durable, not guesses, and not a complete list):"
    ]
    used = len(lines[0])
    added = 0
    for item in items:
        text = _clip_item_text(item.text)
        line = f"- [{item.kind}] {text}"
        # +1 for the newline that will join this row.
        if used + 1 + len(line) > MAX_PROMPT_CHARS:
            break
        lines.append(line)
        used += 1 + len(line)
        added += 1
        if added >= MAX_ITEMS:
            break
    if added == 0:
        return ""
    block = "\n".join(lines)
    return block if len(block) <= MAX_PROMPT_CHARS else block[:MAX_PROMPT_CHARS].rstrip()


def retrieve_relevant_memories(
    store: MemoryStore,
    query: str,
    *,
    items: list[MemoryItem] | None = None,
    query_embedding: list[float] | np.ndarray | None = None,
    now: datetime | None = None,
    limit: int = MAX_ITEMS,
) -> list[MemoryItem]:
    """Return the ranked, thresholded set for this ask. Empty on a clear miss."""
    if not (query or "").strip():
        return []
    pool = items if items is not None else collect_memory_items(store)
    if not pool:
        return []
    scored = score_items(query, pool, query_embedding=query_embedding, now=now)
    return select_relevant(
        scored, has_embeddings=query_embedding is not None, limit=limit
    )


async def retrieve_memories_prompt(
    store: MemoryStore,
    query: str,
    *,
    embed: EmbedFn | None = None,
    embed_available: ModelCheckFn | None = None,
    embed_model: str = DEFAULT_EMBED_MODEL,
    now: datetime | None = None,
) -> str:
    """Build the prompt block, using the CPU embedder when it is already up."""
    items = collect_memory_items(store)
    if not items or not (query or "").strip():
        return ""
    query_embedding = await _maybe_embed_query_and_items(
        query,
        items,
        embed=embed,
        embed_available=embed_available,
        embed_model=embed_model,
    )
    picked = retrieve_relevant_memories(
        store,
        query,
        items=items,
        query_embedding=query_embedding,
        now=now,
    )
    return format_retrieval_block(picked)


async def memories_prompt_for_turn(loop: Any, query: str) -> str:
    """Look up the session store and optional recall embedder, then retrieve."""
    sink = getattr(getattr(loop, "memory", None), "sink", None)
    if not isinstance(sink, MemoryStore):
        return ""
    embed: EmbedFn | None = None
    embed_available: ModelCheckFn | None = None
    embed_model = DEFAULT_EMBED_MODEL
    tools = getattr(loop, "tools", None)
    recall = tools.get("recall") if tools is not None and hasattr(tools, "get") else None
    if recall is not None:
        maybe_embed = getattr(recall, "_embed", None)
        maybe_available = getattr(recall, "_embed_available", None)
        maybe_model = getattr(recall, "_embed_model", None)
        if callable(maybe_embed):
            embed = maybe_embed
        if callable(maybe_available):
            embed_available = maybe_available
        if maybe_model:
            embed_model = str(maybe_model)
    try:
        return await retrieve_memories_prompt(
            sink,
            query,
            embed=embed,
            embed_available=embed_available,
            embed_model=embed_model,
        )
    except Exception:
        log.exception("Could not retrieve relevant memories")
        return ""


async def _maybe_embed_query_and_items(
    query: str,
    items: list[MemoryItem],
    *,
    embed: EmbedFn | None,
    embed_available: ModelCheckFn | None,
    embed_model: str,
) -> list[float] | None:
    """Embed the ask and candidates only when the CPU embed server is ready."""
    if embed is None or not items:
        return None
    if len(items) > _EMBED_BATCH_CAP:
        return None
    available = True
    if embed_available is not None:
        try:
            available = bool(await embed_available())
        except Exception:
            log.exception("Could not check whether the embedder is available")
            return None
    if not available:
        return None
    try:
        vectors = await asyncio.wait_for(
            embed(embed_model, [query, *[item.text for item in items]]),
            timeout=_EMBED_TIMEOUT_S,
        )
    except TimeoutError:
        log.warning(
            "Memory retrieval embedding timed out after %.1fs; "
            "using keyword and recency",
            _EMBED_TIMEOUT_S,
        )
        return None
    except Exception:
        log.exception("Memory retrieval embedding failed; using keyword and recency")
        return None
    if not vectors:
        return None
    query_vec = vectors[0]
    for item, vector in zip(items, vectors[1:], strict=False):
        item.embedding = vector
    return query_vec
