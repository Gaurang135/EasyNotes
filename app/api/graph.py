from __future__ import annotations
from fastapi import APIRouter, Depends
from app.graph.connections import build_connection_graph
from app.api.deps import get_state

router = APIRouter()


@router.get("/graph")
def graph(q: str | None = None, state=Depends(get_state)):
    """Entity-connection graph: documents ↔ extracted entities. `q` highlights
    entities whose value matches."""
    return build_connection_graph(state.conn, q)
