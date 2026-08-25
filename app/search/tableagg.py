"""Deterministic aggregation over extracted table rows for the Ask layer.

Retrieval only ever shows the model a handful of rows from a big table, so any
"sum / average / how many … over a column" question would be computed on a subset and
come out wrong. This module computes those aggregates in code over the COMPLETE table,
so the answer layer can hand the model exact figures instead of letting it add up a
partial view. Pure functions (no DB) so they're easy to test; `table_facts_block`
is the thin adapter that reads tables from the store.
"""
from __future__ import annotations
import re

_OP_AVG = ("average", "avg", "mean")
_OP_SUM = ("total", "sum", "combined", "altogether", "overall")
_OP_COUNT = ("how many", "number of", "count")

# words that never help identify WHICH column/table is meant (operators + filler)
_STOP = {
    "total", "sum", "combined", "altogether", "overall", "average", "avg", "mean", "count",
    "many", "number", "how", "of", "all", "the", "is", "are", "was", "were", "what", "which",
    "in", "on", "do", "did", "i", "have", "my", "a", "an", "there", "across", "and", "for",
    "to", "me", "with",
}
# numeric columns whose name contains one of these are the natural "measure" to sum when the
# table is clearly the subject but the query didn't name a column ("total value of orders").
_MEASURE = ("total", "amount", "value", "price", "salary", "cost", "revenue",
            "spend", "bonus", "qty", "quantity", "sum", "fee", "balance", "score")

_WORD = re.compile(r"[a-z0-9]+")


def _num(v):
    if v is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group()) if m else None


def _op(q: str):
    if any(c in q for c in _OP_AVG):
        return "avg"
    if any(c in q for c in _OP_COUNT):
        return "count"
    if any(c in q for c in _OP_SUM):
        return "sum"
    return None


def _fmt(x: float) -> str:
    return f"{x:,.0f}" if abs(x - round(x)) < 1e-9 else f"{x:,.2f}"


def _find_filter(columns, recs, q):
    """A single 'column = value' filter when a specific cell value appears whole-word in
    the query (e.g. 'Engineering', 'refunded')."""
    for c in columns:
        cn = c["name"]
        seen = set()
        for rec in recs:
            v = str(rec.get(cn, "")).strip()
            k = v.lower()
            if len(v) < 3 or k in seen:
                continue
            seen.add(k)
            if re.search(r"\b" + re.escape(k) + r"\b", q):
                return (cn, v)
    return None


def _numeric_columns(columns, recs):
    """Column names that are numeric for a solid majority of rows (so id-like text is out
    unless it's genuinely numeric)."""
    out = []
    if not recs:
        return out
    for c in columns:
        cn = c["name"]
        nums = [n for n in (_num(r.get(cn)) for r in recs) if n is not None]
        if len(nums) >= max(1, len(recs) * 0.6):
            out.append(cn)
    return out


def _pick_measure(colnames, terms, tname_match):
    """Choose the numeric column: strongest overlap with the query's meaningful terms,
    else — only when the table itself is named — the first measure-like column."""
    best, best_ov = None, 0
    for cn in colnames:
        ov = len(set(_WORD.findall(cn.lower())) & terms)
        if ov > best_ov:
            best, best_ov = cn, ov
    if best_ov > 0:
        return best
    if tname_match:
        for m in _MEASURE:
            for cn in colnames:
                if m in cn.lower():
                    return cn
    return None


def compute_table_facts(tables, query, max_facts: int = 3):
    """Return authoritative fact strings computed over full tables, most-relevant first."""
    q = query.lower()
    op = _op(q)
    if not op:
        return []
    terms = set(_WORD.findall(q)) - _STOP
    scored = []
    for t in tables:
        colnames = [c["name"] for c in t["columns"]]
        recs = [dict(zip(colnames, r)) for r in t["rows"]]
        tname_match = bool(set(_WORD.findall(t["name"].lower())) & terms)
        filt = _find_filter(t["columns"], recs, q)
        sel = [r for r in recs
               if filt is None or str(r.get(filt[0], "")).strip().lower() == filt[1].lower()]
        where = f" where {filt[0]} = {filt[1]}" if filt else ""

        if op == "count":
            if not (tname_match or filt):
                continue
            score = (2 if tname_match else 0) + (1 if filt else 0)
            scored.append((score, f'number of rows in "{t["name"]}"{where} = {len(sel)}'))
            continue

        numeric = _numeric_columns(t["columns"], sel)
        col = _pick_measure(numeric, terms, tname_match)
        if not col:
            continue
        nums = [n for n in (_num(r.get(col)) for r in sel) if n is not None]
        if not nums:
            continue
        val = sum(nums) if op == "sum" else sum(nums) / len(nums)
        overlap = len(set(_WORD.findall(col.lower())) & terms)
        score = overlap * 2 + (2 if tname_match else 0) + (1 if filt else 0)
        scored.append((score, f'{op} of {col} in "{t["name"]}"{where} = {_fmt(val)} '
                              f'(over {len(nums)} rows)'))

    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:max_facts]]


def table_facts_block(conn, query: str) -> str:
    """Load tables from the store and render an authoritative facts block, or '' if none."""
    from app import store
    tables = []
    for t in store.list_tables(conn):
        cr = store.table_columns_and_rows(conn, t["id"])
        if cr:
            tables.append({"name": t["name"], "columns": cr[0], "rows": cr[1]})
    facts = compute_table_facts(tables, query)
    if not facts:
        return ""
    return ("TABLE FACTS (computed in code over the COMPLETE table — authoritative, use these "
            "exact numbers verbatim; never recompute from the excerpts):\n"
            + "\n".join("- " + f for f in facts))
