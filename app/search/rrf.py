from __future__ import annotations


def rrf(rank_lists: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion. Input: per-leg lists of chunk_ids, best-first.
    Output: (chunk_id, score) fused, best-first. No tuning needed; k=60 default."""
    scores: dict[int, float] = {}
    for lst in rank_lists:
        for rank, cid in enumerate(lst):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1])
