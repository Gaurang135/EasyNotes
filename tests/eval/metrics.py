from __future__ import annotations


def recall_at_k(ranked_ids, relevant_ids, k: int) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    top = ranked_ids[:k]
    return len(set(top) & relevant) / len(relevant)


def mrr(ranked_ids, relevant_ids) -> float:
    relevant = set(relevant_ids)
    for i, cid in enumerate(ranked_ids, 1):
        if cid in relevant:
            return 1.0 / i
    return 0.0
