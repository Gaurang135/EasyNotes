from __future__ import annotations
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.deps import get_state

router = APIRouter()


@router.get("/stats")
def stats(state=Depends(get_state)):
    c = state.conn
    by_type = {r[0]: r[1] for r in c.execute(
        "SELECT file_type, count(*) FROM documents GROUP BY file_type")}
    return {
        "documents": c.execute("SELECT count(*) FROM documents").fetchone()[0],
        "ready": c.execute("SELECT count(*) FROM documents WHERE status='ready'").fetchone()[0],
        "chunks": c.execute("SELECT count(*) FROM chunks").fetchone()[0],
        "tables": c.execute("SELECT count(*) FROM tables").fetchone()[0],
        "fields": c.execute("SELECT count(*) FROM fields").fetchone()[0],
        "by_type": by_type,
    }


@router.get("/overview")
def overview(state=Depends(get_state)):
    """Per-document structured summary for the landing dashboard: what each messy
    document was turned into (fields + tables)."""
    c = state.conn
    out = []
    for did, title, ftype, status, err in c.execute(
            "SELECT id,title,file_type,status,error FROM documents ORDER BY id DESC"):
        fields = [{"key": r[0], "value": r[1], "kind": r[2]} for r in c.execute(
            "SELECT key,value,kind FROM fields WHERE document_id=? LIMIT 6", (did,))]
        fcount = c.execute("SELECT count(*) FROM fields WHERE document_id=?", (did,)).fetchone()[0]
        tcount = c.execute("SELECT count(*) FROM tables WHERE document_id=?", (did,)).fetchone()[0]
        out.append({"id": did, "title": title, "file_type": ftype, "status": status, "error": err,
                    "fields": fields, "field_count": fcount, "table_count": tcount})
    return out


@router.get("/documents/{doc_id}/detail")
def document_detail(doc_id: int, state=Depends(get_state)):
    """Everything extracted from one messy document: fields, tables, text preview."""
    c = state.conn
    d = c.execute("SELECT id,title,file_type,status,error FROM documents WHERE id=?",
                  (doc_id,)).fetchone()
    if not d:
        raise HTTPException(404, "not found")
    fields = [{"key": r[0], "value": r[1], "kind": r[2]} for r in c.execute(
        "SELECT key,value,kind FROM fields WHERE document_id=? ORDER BY id", (doc_id,))]
    tables = [{"id": r[0], "name": r[1], "columns": json.loads(r[2]), "row_count": r[3]}
              for r in c.execute(
        "SELECT id,name,columns,row_count FROM tables WHERE document_id=? ORDER BY id", (doc_id,))]
    chunks = [r[0] for r in c.execute(
        "SELECT text FROM chunks WHERE document_id=? ORDER BY seq", (doc_id,))]
    full = "\n\n".join(chunks)
    CAP = 12000
    text = full[:CAP] + ("\n\n… (truncated — full text is indexed)" if len(full) > CAP else "")
    return {"id": d[0], "title": d[1], "file_type": d[2], "status": d[3], "error": d[4],
            "fields": fields, "tables": tables, "text_preview": text, "chunk_count": len(chunks)}


@router.get("/tables")
def list_tables(state=Depends(get_state)):
    rows = state.conn.execute(
        "SELECT t.id, t.document_id, d.title, t.name, t.columns, t.row_count, d.file_type "
        "FROM tables t JOIN documents d ON d.id=t.document_id ORDER BY t.id DESC").fetchall()
    return [{"id": r[0], "document_id": r[1], "document_title": r[2], "name": r[3],
             "columns": json.loads(r[4]), "row_count": r[5], "file_type": r[6]} for r in rows]


def _coerce(val: str, typ: str):
    if typ == "number":
        try:
            return float(str(val).replace(",", "").rstrip("%"))
        except ValueError:
            return None
    return str(val).lower()


@router.get("/tables/{table_id}/rows")
def query_rows(table_id: int, col: str | None = None, op: str = "contains",
               val: str | None = None, sort: str | None = None, dir: str = "asc",
               limit: int = 50, offset: int = 0, state=Depends(get_state)):
    meta = state.conn.execute("SELECT columns FROM tables WHERE id=?", (table_id,)).fetchone()
    if not meta:
        raise HTTPException(404, "table not found")
    columns = json.loads(meta[0])
    names = [c["name"] for c in columns]
    types = {c["name"]: c["type"] for c in columns}
    rows = [json.loads(r[0]) for r in state.conn.execute(
        "SELECT data FROM table_rows WHERE table_id=? ORDER BY row_index", (table_id,))]

    if col and col in names and val not in (None, ""):
        i = names.index(col); typ = types[col]
        target = _coerce(val, typ)

        def keep(r):
            cell = r[i] if i < len(r) else ""
            if typ == "number":
                cv = _coerce(cell, "number")
                if cv is None or target is None:
                    return False
                return {"gte": cv >= target, "lte": cv <= target, "eq": cv == target,
                        "contains": str(target) in str(cell).lower()}.get(op, True)
            cv = str(cell).lower()
            return {"eq": cv == target, "contains": target in cv}.get(op, target in cv)
        rows = [r for r in rows if keep(r)]

    if sort and sort in names:
        i = names.index(sort); typ = types[sort]
        rows.sort(key=lambda r: (_coerce(r[i] if i < len(r) else "", typ) or 0) if typ == "number"
                  else str(r[i] if i < len(r) else "").lower(), reverse=(dir == "desc"))

    total = len(rows)
    return {"columns": columns, "rows": rows[offset:offset + limit], "total": total}


@router.get("/fields")
def list_fields(kind: str | None = None, q: str | None = None, limit: int = 200,
                state=Depends(get_state)):
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
    rows = state.conn.execute(sql, params).fetchall()
    return [{"document_id": r[0], "document_title": r[1], "key": r[2], "value": r[3], "kind": r[4]}
            for r in rows]
