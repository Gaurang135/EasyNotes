from __future__ import annotations


def rrf(rank_lists: list[list[int]], k: int = 60,
        weights: list[float] | None = None) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion. Input: per-leg lists of chunk_ids, best-first.
    Output: (chunk_id, score) fused, best-first. No tuning needed; k=60 default.
    Optional per-leg weights let a high-precision leg (e.g. title match) count for more."""
    ws = weights or [1.0] * len(rank_lists)
    scores: dict[int, float] = {}
    for lst, w in zip(rank_lists, ws):
        for rank, cid in enumerate(lst):
            scores[cid] = scores.get(cid, 0.0) + w / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1])
