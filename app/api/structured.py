from __future__ import annotations
import json
import re
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.deps import get_state

router = APIRouter()

# a pair whose key names the paying/selling entity, used to attribute spend to a source
_VENDOR_KEY = re.compile(
    r"vendor|restaurant|merchant|company|supplier|seller|legal entity|store|shop|biller|from",
    re.I)
_CURRENCY = [("₹", "₹"), ("inr", "₹"), ("rs", "₹"), ("$", "$"), ("usd", "$"),
             ("€", "€"), ("eur", "€"), ("£", "£"), ("gbp", "£")]


def _parse_amount(value: str):
    """Best-effort numeric value from a messy amount string ('INR 470.42', 'Rs.2,742.00').
    Matches the number itself so a currency prefix like 'Rs.' can't leak a stray dot."""
    m = re.search(r"\d[\d,]*(?:\.\d+)?", value or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _currency(values: list[str]) -> str:
    for v in values:
        low = v.lower()
        for token, sym in _CURRENCY:
            if token in low:
                return sym
    return ""


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
        # lets the UI default the landing to Ask only when a generation model is configured
        "ask_enabled": getattr(state, "answer_synth", None) is not None,
    }


@router.get("/insights")
def insights(state=Depends(get_state)):
    """Exact, AI-free analytics computed from the extracted structured data — so the numbers
    are accurate and free (an LLM would miscount). Adapts to whatever was extracted: spend
    totals + by-source + over-time when amounts exist, plus field/type breakdowns."""
    c = state.conn
    docs = c.execute("SELECT id, title, file_type FROM documents WHERE status='ready'").fetchall()
    title = {d[0]: d[1] for d in docs}
    by_type: dict = {}
    for _, _, ft in docs:
        by_type[ft] = by_type.get(ft, 0) + 1
    field_kinds = {r[0]: r[1] for r in c.execute(
        "SELECT kind, COUNT(*) FROM fields GROUP BY kind ORDER BY 2 DESC")}

    amount_vals = c.execute("SELECT document_id, value FROM fields WHERE kind='amount'").fetchall()
    # a document's spend = its largest amount (line items ≤ the total), so multi-amount
    # invoices don't double-count and single-amount receipts stay exact
    doc_amt: dict = {}
    for did, val in amount_vals:
        n = _parse_amount(val)
        if n is not None:
            doc_amt[did] = max(doc_amt.get(did, 0.0), n)

    doc_vendor: dict = {}
    for did, key, value in c.execute("SELECT document_id, key, value FROM fields WHERE kind='pair'"):
        if did not in doc_vendor and _VENDOR_KEY.search(key or ""):
            doc_vendor[did] = value.strip()

    by_vendor_map: dict = defaultdict(lambda: [0.0, 0])   # name -> [total, count]
    for did, amt in doc_amt.items():
        name = doc_vendor.get(did) or title.get(did, "Unknown")
        by_vendor_map[name][0] += amt
        by_vendor_map[name][1] += 1
    by_vendor = sorted(
        ({"name": n, "total": round(t, 2), "count": ct} for n, (t, ct) in by_vendor_map.items()),
        key=lambda x: -x["total"])[:8]

    # spend per month, from each document's earliest ISO date
    doc_month: dict = {}
    for did, value in c.execute("SELECT document_id, value FROM fields WHERE kind='date' ORDER BY value"):
        m = re.search(r"(\d{4})-(\d{2})", value or "")
        if m and did not in doc_month:
            doc_month[did] = f"{m.group(1)}-{m.group(2)}"
    month_map: dict = defaultdict(float)
    for did, amt in doc_amt.items():
        if did in doc_month:
            month_map[doc_month[did]] += amt
    over_time = [{"month": m, "total": round(month_map[m], 2)} for m in sorted(month_map)]

    dates = [r[0] for r in c.execute(
        "SELECT value FROM fields WHERE kind='date' AND value GLOB '[0-9][0-9][0-9][0-9]-*' ORDER BY value")]
    amounts = [n for n in (doc_amt.values())]

    # dimensions that make non-financial docs (specs, collections, notes) insightful too
    activity: dict = defaultdict(int)                 # count of dated items per month
    for (value,) in c.execute("SELECT value FROM fields WHERE kind='date'"):
        m = re.search(r"(\d{4})-(\d{2})", value or "")
        if m:
            activity[f"{m.group(1)}-{m.group(2)}"] += 1
    contacts = {
        "emails": c.execute("SELECT COUNT(DISTINCT value) FROM fields WHERE kind='email'").fetchone()[0],
        "phones": c.execute("SELECT COUNT(DISTINCT value) FROM fields WHERE kind='phone'").fetchone()[0],
        "links": c.execute("SELECT COUNT(DISTINCT value) FROM fields WHERE kind='url'").fetchone()[0],
    }
    # the structured attributes that recur across documents (by how many docs carry each)
    top_attributes = [{"key": k, "docs": n} for k, n in c.execute(
        "SELECT key, COUNT(DISTINCT document_id) FROM fields WHERE kind='pair' "
        "GROUP BY key ORDER BY 2 DESC, key LIMIT 8")]
    tbl = c.execute("SELECT COUNT(*), COALESCE(SUM(row_count), 0) FROM tables").fetchone()

    return {
        "documents": len(docs),
        "by_type": by_type,
        "field_kinds": field_kinds,
        "currency": _currency([v for _, v in amount_vals]),
        "amount": {
            "docs_with_amount": len(doc_amt),
            "total": round(sum(amounts), 2) if amounts else 0,
            "avg": round(sum(amounts) / len(amounts), 2) if amounts else 0,
            "min": round(min(amounts), 2) if amounts else 0,
            "max": round(max(amounts), 2) if amounts else 0,
        },
        "distinct_vendors": len({v for v in doc_vendor.values()}),
        "date_range": {"min": dates[0], "max": dates[-1]} if dates else None,
        "by_vendor": by_vendor,
        "over_time": over_time,
        "activity": [{"month": m, "count": activity[m]} for m in sorted(activity)],
        "contacts": contacts,
        "top_attributes": top_attributes,
        "tables": {"count": tbl[0], "rows": tbl[1]},
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
