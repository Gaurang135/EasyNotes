from __future__ import annotations
from fastapi import APIRouter, Depends, Response
from app.graph.export import to_cytoscape, to_graphml
from app.search.service import run_search
from app.models import SearchFilter
from app.api.deps import get_state

router = APIRouter()


@router.get("/graph")
def graph(q: str | None = None, state=Depends(get_state)):
    matched = None
    if q:
        hits = run_search(state.conn, state.embedder, state.vector_index, state.fts_index,
                          query=q, mode="hybrid", flt=SearchFilter(), limit=100, offset=0)
        matched = {h.chunk_id: h.score for h in hits}
    return to_cytoscape(state.conn, matched)


@router.get("/graph/export")
def graph_export(state=Depends(get_state)):
    return Response(to_graphml(state.conn), media_type="application/graphml+xml")
