from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api.deps import get_state

router = APIRouter()


class AnswerReq(BaseModel):
    q: str
    mode: str = "hybrid"


@router.post("/answer")
def answer(body: AnswerReq, state=Depends(get_state)):
    # The retrieval half is ready and shared with /search; only generation is absent.
    raise HTTPException(
        status_code=501,
        detail=("Answer synthesis is not enabled. EasyNotes is LLM-free by default. "
                "To enable: add a synthesizer module that calls run_search() (already the "
                "shared retrieval function) and set an LLM API key. See DECISIONS.md."))
