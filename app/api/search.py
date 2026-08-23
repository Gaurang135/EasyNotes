from __future__ import annotations
from fastapi import APIRouter, Depends
from app.models import SearchFilter
from app.search.service import run_search, answer_from_fields
from app.api.deps import get_state

router = APIRouter()


@router.get("/search")
def search(q: str, mode: str = "hybrid", type: str | None = None, doc_id: int | None = None,
           limit: int = 20, offset: int = 0, state=Depends(get_state)):
    flt = SearchFilter(file_type=type, doc_id=doc_id)
    hits = run_search(state.conn, state.embedder, state.vector_index, state.fts_index,
                      query=q, mode=mode, flt=flt, limit=limit, offset=offset)
    answers = answer_from_fields(state.conn, q, flt)
    return {"query": q, "mode": mode, "answers": answers, "results": [
        {"chunk_id": h.chunk_id, "document_id": h.document_id, "document_title": h.document_title,
         "file_type": h.file_type, "snippet": h.snippet, "location": h.location,
         "score": h.score} for h in hits]}
