"""Pure, FastAPI-free table querying — filter + sort + paginate extracted table rows.

Kept out of the HTTP layer so the query engine (Mode A: precise/defined queries) is
unit-testable on plain data, and the router only shapes the request/response.
"""
from __future__ import annotations


def _coerce(val, typ: str):
    if typ == "number":
        try:
            return float(str(val).replace(",", "").rstrip("%"))
        except ValueError:
            return None
    return str(val).lower()


def query_table(columns: list[dict], rows: list[list], *, col: str | None = None,
                op: str = "contains", val: str | None = None, sort: str | None = None,
                dir: str = "asc", limit: int = 50, offset: int = 0) -> dict:
    """Filter rows by a column/op/value, optionally sort, then paginate.
    columns: [{name, type}]; rows: row-major list of cell lists. Returns {columns, rows, total}."""
    names = [c["name"] for c in columns]
    types = {c["name"]: c["type"] for c in columns}

    if col and col in names and val not in (None, ""):
        i = names.index(col)
        typ = types[col]
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
        i = names.index(sort)
        typ = types[sort]
        rows = sorted(
            rows,
            key=lambda r: (_coerce(r[i] if i < len(r) else "", typ) or 0) if typ == "number"
            else str(r[i] if i < len(r) else "").lower(),
            reverse=(dir == "desc"))

    total = len(rows)
    return {"columns": columns, "rows": rows[offset:offset + limit], "total": total}
