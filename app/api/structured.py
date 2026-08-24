from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app import store
from app.api.deps import get_state
from app.api.schemas import OverviewItem, DetailOut, TableInfo, FieldRow
from app.search.tablequery import query_table

router = APIRouter()


@router.get("/stats")
def stats(state=Depends(get_state)):
    return {**store.stats(state.conn),
            # lets the UI default the landing to Ask only when a generation model is configured
            "ask_enabled": getattr(state, "answer_synth", None) is not None}


@router.get("/overview", response_model=list[OverviewItem])
def overview(state=Depends(get_state)):
    """Per-document structured summary — what each messy document was turned into (curated
    fields, typed kinds first, plus a summary of every extracted table)."""
    return store.overview(state.conn)


@router.get("/documents/{doc_id}/detail", response_model=DetailOut)
def document_detail(doc_id: int, state=Depends(get_state)):
    """Everything extracted from one messy document: fields, tables, and a text preview."""
    detail = store.document_detail(state.conn, doc_id)
    if detail is None:
        raise HTTPException(404, "not found")
    return detail


@router.get("/tables", response_model=list[TableInfo])
def list_tables(state=Depends(get_state)):
    return store.list_tables(state.conn)


@router.get("/tables/{table_id}/rows")
def query_rows(table_id: int, col: str | None = None, op: str = "contains",
               val: str | None = None, sort: str | None = None, dir: str = "asc",
               limit: int = 50, offset: int = 0, state=Depends(get_state)):
    cr = store.table_columns_and_rows(state.conn, table_id)
    if cr is None:
        raise HTTPException(404, "table not found")
    columns, rows = cr
    return query_table(columns, rows, col=col, op=op, val=val, sort=sort, dir=dir,
                       limit=limit, offset=offset)


@router.get("/fields", response_model=list[FieldRow])
def list_fields(kind: str | None = None, q: str | None = None, limit: int = 200,
                state=Depends(get_state)):
    return store.search_fields(state.conn, kind, q, limit)
