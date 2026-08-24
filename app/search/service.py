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


_AGG_CUES = [
    "how many", "how much total", "count", "number of", "list all", "list the",
    "list every", "all the", "every ", "distinct", "unique", "total number",
    "which companies", "which vendors", "how many invoices", "across all", "sum of",
    "average", "breakdown", "group by", "each ",
    # item / purchase listing ("what all items i bought", "what products did I buy")
    "what all", "bought", "did i buy", "purchase", "product", "line item", "items",
]


def detect_aggregate_intent(query: str) -> bool:
    """Count/list-all/distinct questions can't be answered from a retrieval sample —
    they need the whole corpus. Detect them so /answer switches to structured context."""
    q = " " + query.lower() + " "
    return any(c in q for c in _AGG_CUES)


# Cue words that signal a question is about named entities (extracted as `pair` fields:
# vendors, clients, owners, …) or wants an exhaustive list of them.
_PAIR_CUES = ["compan", "vendor", "supplier", "client", "customer", "owner", "buyer",
              "seller", "who ", "whom", "name", "entit", "organi", "party", "parties",
              "distinct", "unique", "list all", "list the", "list every"]


def _target_kinds(query: str) -> set[str]:
    """Which extracted-field kinds an aggregate question is asking about, so the inventory
    can include ALL of those (uncapped) instead of a starved sample of every kind."""
    kinds = set(detect_field_intents(query))          # amount / date / email / phone / url
    q = " " + query.lower() + " "
    if any(c in q for c in _PAIR_CUES):
        kinds.add("pair")
    return kinds


# field kinds, most→least specific: items/entities answer most listing questions; the
# long amount/date runs are bulkier and, within a document, least likely to be the target
_KIND_SPECIFICITY = {"item": 0, "pair": 1, "email": 2, "url": 3, "phone": 4, "date": 5, "amount": 6}


def structured_context(conn, query: str = "", max_chars: int = 11000,
                       fields_per_doc: int = 15) -> str:
    """A per-document inventory of the corpus so the model can compute counts / distinct
    lists / totals over ALL the data (not a retrieval sample) and cite the exact document
    each fact came from. Query-aware: it includes the field(s) of the kind(s) the question
    targets, grouped by document.

    Two guards keep it inside a provider's request limit without ever dropping the answer:
    each document is capped at fields_per_doc fields (most-specific kinds first, so one
    field-heavy document — e.g. meeting notes with 200 pairs — can't crowd everything out),
    and documents are ordered by how relevant they are (item-bearing first, then by field
    count) before the whole thing is capped at max_chars. The header always states the true
    total so counting stays exact even if some low-relevance documents are omitted."""
    docs = conn.execute(
        "SELECT id, title, file_type FROM documents WHERE status='ready'").fetchall()
    total = len(docs)
    kinds = _target_kinds(query)
    by_doc: dict = {}
    if kinds:
        qs = ",".join("?" * len(kinds))
        for did, key, value, kind in conn.execute(
                f"SELECT document_id, key, value, kind FROM fields WHERE kind IN ({qs})",
                tuple(kinds)):
            disp = f"{key}={value}" if kind in ("pair", "item") else f"{kind}={value}"
            by_doc.setdefault(did, []).append((_KIND_SPECIFICITY.get(kind, 9), disp))
    for did, fields in by_doc.items():
        fields.sort(key=lambda kv: kv[0])           # most-specific kinds survive the per-doc cap
        del fields[fields_per_doc:]

    def item_count(did):
        return sum(1 for spec, _ in by_doc.get(did, []) if spec == 0)
    # item-bearing docs first, then field-richest — so the size cap sheds least-relevant docs
    docs.sort(key=lambda d: (-item_count(d[0]), -len(by_doc.get(d[0], [])), d[2], d[1]))
    header = (f"CORPUS INVENTORY — {total} documents (the whole corpus). "
              "Format: title [type] :: field=value; …")
    lines, used, omitted = [header], len(header), 0
    for did, title, ft in docs:
        fields = by_doc.get(did)
        line = f"- {title} [{ft}]" + (" :: " + "; ".join(d for _, d in fields) if fields else "")
        if used + len(line) + 1 > max_chars:
            omitted += 1
            continue
        lines.append(line)
        used += len(line) + 1
    if omitted:
        lines.append(f"(+{omitted} more document(s) omitted to fit the size limit)")
    return "\n".join(lines)


def content_terms(query: str) -> list[str]:
    """Query terms worth anchoring on: non-stopword, length>1, longest first."""
    terms = [t for t in re.findall(r"\w+", query.lower()) if t not in STOPWORDS and len(t) > 1]
    return sorted(set(terms), key=len, reverse=True)


# LLM-free query router: map natural-language intent to an extracted field kind, so
# "total amount in invoices" returns the amount values directly (Mode A), not passages.
FIELD_INTENTS = {
    "item": ["item", "items", "product", "bought", "buy", "purchase", "line item", "goods"],
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
