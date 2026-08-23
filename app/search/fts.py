from __future__ import annotations
import re
import sqlite3
from app.models import ScoredChunk, SearchFilter

_TOKEN = re.compile(r'"[^"]*"|\S+')
_KEEP = {"AND", "OR", "NOT", "NEAR"}


def sanitize_fts_query(raw: str) -> str:
    """Make any user string safe for FTS5 MATCH while preserving quoted phrases
    and top-level uppercase boolean operators. Datasette-style."""
    if not raw or not raw.strip():
        return '""'
    out: list[str] = []
    for tok in _TOKEN.findall(raw):
        if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
            inner = tok[1:-1].replace('"', '""')
            if inner.strip():
                out.append(f'"{inner}"')
            continue
        if tok in _KEEP:
            out.append(tok)
            continue
        cleaned = tok.replace('"', '""')
        out.append(f'"{cleaned}"')
    return " ".join(out) or '""'


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

    def delete_document(self, document_id: int) -> None:
        # chunks_fts is external-content: deleting chunks rows fires the AFTER DELETE trigger
        self.conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
        self.conn.commit()
