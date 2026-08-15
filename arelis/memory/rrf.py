"""Reciprocal rank fusion for keyword and vector recall hits."""

from __future__ import annotations

from arelis.memory.store import SearchHit

_RRF_K = 60


def merge_ranked_hits(
    *ranked_lists: list[SearchHit],
    limit: int = 20,
    k: int = _RRF_K,
) -> list[SearchHit]:
    """Merge ranked hit lists by reciprocal rank. First occurrence wins for payload."""
    scores: dict[str, float] = {}
    by_id: dict[str, SearchHit] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits):
            key = hit.hit_key
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            by_id.setdefault(key, hit)
    ordered = sorted(scores.keys(), key=lambda key: scores[key], reverse=True)
    return [by_id[key] for key in ordered[:limit]]
