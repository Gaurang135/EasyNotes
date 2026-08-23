from __future__ import annotations
from app.models import SearchHit, SearchFilter
from app.search.fts import sanitize_fts_query
from app.search.rrf import rrf

FUSION_DEPTH = 100


def _passes_filter(conn, chunk_ids, flt: SearchFilter):
    if not chunk_ids or (not flt.file_type and not flt.doc_id):
        return set(chunk_ids)
    qs = ",".join("?" * len(chunk_ids))
    sql = (f"SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id "
           f"WHERE c.id IN ({qs})")
    params = list(chunk_ids)
    if flt.file_type:
        sql += " AND d.file_type=?"; params.append(flt.file_type)
    if flt.doc_id:
        sql += " AND c.document_id=?"; params.append(flt.doc_id)
    return {r[0] for r in conn.execute(sql, params)}


def _snippet(text: str, query: str, width: int = 200) -> str:
    low = text.lower()
    for term in query.lower().split():
        i = low.find(term)
        if i >= 0:
            start = max(0, i - width // 2)
            return ("…" if start else "") + text[start:start + width].strip() + "…"
    return text[:width].strip() + ("…" if len(text) > width else "")


def _hydrate(conn, ordered_ids, scores, query) -> list[SearchHit]:
    hits = []
    for cid in ordered_ids:
        row = conn.execute(
            "SELECT c.document_id, d.title, d.file_type, c.text, c.location "
            "FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id=?",
            (cid,)).fetchone()
        if not row:
            continue
        doc_id, title, ftype, text, loc = row
        hits.append(SearchHit(chunk_id=cid, document_id=doc_id, document_title=title,
                              file_type=ftype, snippet=_snippet(text, query),
                              text=text, location=loc, score=scores.get(cid, 0.0)))
    return hits


def run_search(conn, embedder, vector_index, fts_index, *, query, mode, flt, limit, offset):
    if mode == "keyword":
        scored = fts_index.search(sanitize_fts_query(query), flt, FUSION_DEPTH, 0)
        ordered = [s.chunk_id for s in scored]
        scores = {s.chunk_id: s.score for s in scored}
    elif mode == "semantic":
        qv = embedder.embed_query(query)
        scored = vector_index.search(qv, FUSION_DEPTH)
        allowed = _passes_filter(conn, [s.chunk_id for s in scored], flt)
        scored = [s for s in scored if s.chunk_id in allowed]
        ordered = [s.chunk_id for s in scored]
        scores = {s.chunk_id: s.score for s in scored}
    else:  # hybrid
        kw = fts_index.search(sanitize_fts_query(query), flt, FUSION_DEPTH, 0)
        qv = embedder.embed_query(query)
        sem = vector_index.search(qv, FUSION_DEPTH)
        allowed = _passes_filter(conn, [s.chunk_id for s in sem], flt)
        sem = [s for s in sem if s.chunk_id in allowed]
        fused = rrf([[s.chunk_id for s in kw], [s.chunk_id for s in sem]])
        ordered = [cid for cid, _ in fused]
        scores = dict(fused)
    page = ordered[offset:offset + limit]
    return _hydrate(conn, page, scores, query)
