"""Read repository — every document/field/table SELECT lives here, so routers don't
hand-write SQL and positional tuple-unpacking. Returns plain dicts shaped for the API."""
from __future__ import annotations
import json

# high-signal kinds first so a Record card leads with the meaningful fields, pairs last
_KIND_PRIORITY = {"amount": 0, "date": 1, "email": 2, "phone": 3, "url": 4, "item": 5, "pair": 6}
_DETAIL_CAP = 12000


def stats(conn) -> dict:
    by_type = {r[0]: r[1] for r in conn.execute(
        "SELECT file_type, count(*) FROM documents GROUP BY file_type")}
    return {
        "documents": conn.execute("SELECT count(*) FROM documents").fetchone()[0],
        "ready": conn.execute("SELECT count(*) FROM documents WHERE status='ready'").fetchone()[0],
        "chunks": conn.execute("SELECT count(*) FROM chunks").fetchone()[0],
        "tables": conn.execute("SELECT count(*) FROM tables").fetchone()[0],
        "fields": conn.execute("SELECT count(*) FROM fields").fetchone()[0],
        "by_type": by_type,
        "field_kinds": {r[0]: r[1] for r in conn.execute(
            "SELECT kind, COUNT(*) FROM fields GROUP BY kind")},
    }


def list_documents(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT d.id,d.title,d.file_type,d.status,d.error,d.uploaded_at,d.size,"
        " (SELECT COUNT(*) FROM fields f WHERE f.document_id=d.id),"
        " (SELECT COUNT(*) FROM tables t WHERE t.document_id=d.id)"
        " FROM documents d ORDER BY d.id DESC").fetchall()
    return [{"id": r[0], "title": r[1], "file_type": r[2], "status": r[3], "error": r[4],
             "uploaded_at": r[5], "size": r[6], "field_count": r[7], "table_count": r[8]}
            for r in rows]


def get_document(conn, doc_id: int) -> dict | None:
    r = conn.execute(
        "SELECT id,title,file_type,status,error,warnings FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "title": r[1], "file_type": r[2], "status": r[3],
            "error": r[4], "warnings": json.loads(r[5] or "[]")}


def document_exists(conn, doc_id: int) -> bool:
    return conn.execute("SELECT 1 FROM documents WHERE id=?", (doc_id,)).fetchone() is not None


def original_filename(conn, doc_id: int) -> str | None:
    r = conn.execute("SELECT filename FROM documents WHERE id=?", (doc_id,)).fetchone()
    return r[0] if r else None


def overview(conn) -> list[dict]:
    out = []
    for did, title, ftype, status, err in conn.execute(
            "SELECT id,title,file_type,status,error FROM documents ORDER BY id DESC"):
        rows = conn.execute("SELECT key,value,kind FROM fields WHERE document_id=?", (did,)).fetchall()
        rows.sort(key=lambda r: _KIND_PRIORITY.get(r[2], 9))
        fields = [{"key": k, "value": v, "kind": kd} for k, v, kd in rows[:10]]
        tables = [{"id": r[0], "name": r[1], "row_count": r[2]} for r in conn.execute(
            "SELECT id,name,row_count FROM tables WHERE document_id=? ORDER BY id", (did,))]
        out.append({"id": did, "title": title, "file_type": ftype, "status": status, "error": err,
                    "fields": fields, "field_count": len(rows),
                    "table_count": len(tables), "tables": tables})
    return out


def document_detail(conn, doc_id: int) -> dict | None:
    d = conn.execute("SELECT id,title,file_type,status,error FROM documents WHERE id=?",
                     (doc_id,)).fetchone()
    if not d:
        return None
    fields = [{"key": r[0], "value": r[1], "kind": r[2]} for r in conn.execute(
        "SELECT key,value,kind FROM fields WHERE document_id=? ORDER BY id", (doc_id,))]
    tables = [{"id": r[0], "name": r[1], "columns": json.loads(r[2]), "row_count": r[3]}
              for r in conn.execute(
        "SELECT id,name,columns,row_count FROM tables WHERE document_id=? ORDER BY id", (doc_id,))]
    chunks = [r[0] for r in conn.execute(
        "SELECT text FROM chunks WHERE document_id=? ORDER BY seq", (doc_id,))]
    full = "\n\n".join(chunks)
    text = full[:_DETAIL_CAP] + ("\n\n… (truncated — full text is indexed)" if len(full) > _DETAIL_CAP else "")
    return {"id": d[0], "title": d[1], "file_type": d[2], "status": d[3], "error": d[4],
            "fields": fields, "tables": tables, "text_preview": text, "chunk_count": len(chunks)}


def list_tables(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT t.id, t.document_id, d.title, t.name, t.columns, t.row_count, d.file_type "
        "FROM tables t JOIN documents d ON d.id=t.document_id ORDER BY t.id DESC").fetchall()
    return [{"id": r[0], "document_id": r[1], "document_title": r[2], "name": r[3],
             "columns": json.loads(r[4]), "row_count": r[5], "file_type": r[6]} for r in rows]


def table_columns_and_rows(conn, table_id: int):
    meta = conn.execute("SELECT columns FROM tables WHERE id=?", (table_id,)).fetchone()
    if not meta:
        return None
    columns = json.loads(meta[0])
    rows = [json.loads(r[0]) for r in conn.execute(
        "SELECT data FROM table_rows WHERE table_id=? ORDER BY row_index", (table_id,))]
    return columns, rows


def search_fields(conn, kind: str | None, q: str | None, limit: int) -> list[dict]:
    sql = ("SELECT f.document_id, d.title, f.key, f.value, f.kind FROM fields f "
           "JOIN documents d ON d.id=f.document_id")
    conds, params = [], []
    if kind:
        conds.append("f.kind=?"); params.append(kind)
    if q:
        conds.append("(f.value LIKE ? OR f.key LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY f.id DESC LIMIT ?"; params.append(limit)
    return [{"document_id": r[0], "document_title": r[1], "key": r[2], "value": r[3], "kind": r[4]}
            for r in conn.execute(sql, params)]
