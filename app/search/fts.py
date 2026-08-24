from __future__ import annotations
import re
import sqlite3
from app.models import ScoredChunk, SearchFilter

_TOKEN = re.compile(r'"[^"]*"|\S+')
_KEEP = {"AND", "OR", "NOT", "NEAR"}

# Stopwords dropped from natural-language queries so a question like "who is free"
# searches on "free", not on who/is. Shared with search snippet-anchoring.
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am", "im", "i",
    "who", "what", "when", "where", "why", "how", "which", "whom",
    "of", "to", "in", "on", "at", "for", "and", "or", "but", "if", "it", "its",
    "this", "that", "these", "those", "as", "by", "with", "from", "do", "does",
    "did", "can", "could", "will", "would", "my", "me", "you", "your", "we",
}


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def sanitize_fts_query(raw: str) -> str:
    """Make any user string safe for FTS5 MATCH.

    Plain natural-language questions are the common case: we drop stopwords and OR the
    remaining terms so "who is free" matches any chunk containing "free" (BM25 then ranks
    denser/rarer matches higher) — rather than the old implicit AND of every word, which
    required who AND is AND free in one chunk and usually matched nothing.

    Power-user syntax is respected: if the query already uses quotes or an explicit
    AND/OR/NOT/NEAR operator, its structure is preserved (terms just get quoted safely)."""
    if not raw or not raw.strip():
        return '""'
    tokens = _TOKEN.findall(raw)
    explicit = any(t in _KEEP for t in tokens) or any(
        t.startswith('"') and t.endswith('"') and len(t) >= 2 for t in tokens)
    if explicit:
        out: list[str] = []
        for tok in tokens:
            if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
                inner = tok[1:-1].replace('"', '""')
                if inner.strip():
                    out.append(f'"{inner}"')
            elif tok in _KEEP:
                out.append(tok)
            else:
                out.append(_quote(tok))
        return " ".join(out) or '""'
    # natural language: drop stopwords, OR the rest (fall back to all terms if all were stopwords)
    terms = [t for t in tokens if re.sub(r"\W", "", t)]
    content = [t for t in terms if t.lower() not in STOPWORDS]
    use = content or terms
    return " OR ".join(_quote(t) for t in use) or '""'


class Fts5Index:
    def __init__(self, conn):
        self.conn = conn

    def search(self, query: str, flt: SearchFilter, limit: int, offset: int) -> list[ScoredChunk]:
        sql = ("SELECT c.id, rank FROM chunks_fts "
               "JOIN chunks c ON c.id = chunks_fts.rowid "
               "JOIN documents d ON d.id = c.document_id "
               "WHERE chunks_fts MATCH ?")
        params: list = [query]
        if flt.file_type:
            sql += " AND d.file_type = ?"; params.append(flt.file_type)
        if flt.doc_id:
            sql += " AND c.document_id = ?"; params.append(flt.doc_id)
        sql += " ORDER BY rank LIMIT ? OFFSET ?"
        params += [limit, offset]
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # last-resort backstop: fully-quoted retry
            params[0] = '"' + query.replace('"', "") + '"'
            rows = self.conn.execute(sql, params).fetchall()
        # bm25 'rank' is negative-is-better; flip to higher-is-better
        return [ScoredChunk(chunk_id=cid, score=-rank) for cid, rank in rows]
