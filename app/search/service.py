from __future__ import annotations
import re
from app.models import SearchHit, SearchFilter
from app.search.fts import sanitize_fts_query
from app.search.rrf import rrf

FUSION_DEPTH = 100

# Stopwords are ignored when anchoring/ highlighting snippets, so a query like
# "who is free" centers on "free", not on the first "is".
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am", "im", "i",
    "who", "what", "when", "where", "why", "how", "which", "whom",
    "of", "to", "in", "on", "at", "for", "and", "or", "but", "if", "it", "its",
    "this", "that", "these", "those", "as", "by", "with", "from", "do", "does",
    "did", "can", "could", "will", "would", "my", "me", "you", "your", "we",
}


def content_terms(query: str) -> list[str]:
    """Query terms worth anchoring on: non-stopword, length>1, longest first."""
    terms = [t for t in re.findall(r"\w+", query.lower()) if t not in STOPWORDS and len(t) > 1]
    return sorted(set(terms), key=len, reverse=True)


# LLM-free query router: map natural-language intent to an extracted field kind, so
# "total amount in invoices" returns the amount values directly (Mode A), not passages.
FIELD_INTENTS = {
    "amount": ["amount", "total", "price", "cost", "sum", "paid", "payable", "due",
               "how much", "rupee", "dollar", "rs", "inr", "usd", "₹", "$"],
    "date": ["date", "when", "due date", "deadline", "day", "dated"],
    "email": ["email", "e-mail", "mail id", "mail-id"],
    "phone": ["phone", "mobile", "contact number", "call", "telephone"],
    "url": ["url", "link", "website", "site", "web address"],
}


def detect_field_intents(query: str) -> list[str]:
    q = " " + query.lower() + " "
    hits = [kind for kind, kws in FIELD_INTENTS.items() if any(k in q for k in kws)]
    return hits


def answer_from_fields(conn, query: str, flt: SearchFilter, limit: int = 12) -> list[dict]:
    """Direct structured answers pulled from extracted fields when the query asks for
    a known field kind. LLM-free."""
    kinds = detect_field_intents(query)
    if not kinds:
        return []
    qs = ",".join("?" * len(kinds))
    sql = ("SELECT f.value, f.kind, f.document_id, d.title FROM fields f "
           "JOIN documents d ON d.id=f.document_id WHERE f.kind IN (" + qs + ")")
    params = list(kinds)
    if flt.doc_id:
        sql += " AND f.document_id=?"; params.append(flt.doc_id)
    if flt.file_type:
        sql += " AND d.file_type=?"; params.append(flt.file_type)
    sql += " ORDER BY f.id LIMIT ?"; params.append(limit)
    return [{"value": r[0], "kind": r[1], "document_id": r[2], "document_title": r[3]}
            for r in conn.execute(sql, params)]


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


def _snippet(text: str, query: str, width: int = 220) -> str:
    low = text.lower()
    # anchor on the most meaningful query term present, not the first stopword
    for term in content_terms(query):
        i = low.find(term)
        if i >= 0:
            start = max(0, i - width // 3)
            end = start + width
            return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")
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
