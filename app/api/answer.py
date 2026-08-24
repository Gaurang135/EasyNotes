from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.models import SearchFilter
from app.search.service import run_search
from app.api.deps import get_state

router = APIRouter()


class AnswerReq(BaseModel):
    q: str
    mode: str = "hybrid"


@router.post("/answer")
def answer(body: AnswerReq, state=Depends(get_state)):
    synth = getattr(state, "answer_synth", None)
    if synth is None:
        raise HTTPException(
            status_code=501,
            detail=("Answer synthesis (LLM) is not enabled. EasyNotes is LLM-free by "
                    "default — retrieval works without it. To turn on grounded answers, "
                    "set ANSWER_MODEL and ANSWER_API_KEY (e.g. Groq free tier: "
                    "ANSWER_BASE_URL=https://api.groq.com/openai/v1) or point ANSWER_BASE_URL "
                    "at a local Ollama. See README."))
    hits = run_search(state.conn, state.embedder, state.vector_index, state.fts_index,
                      query=body.q, mode=body.mode, flt=SearchFilter(), limit=6, offset=0)
    if not hits:
        return {"question": body.q, "answer": "I couldn't find anything relevant in your documents.",
                "citations": []}
    try:
        result = synth.answer(body.q, hits)
    except Exception as e:                       # provider/network errors never 500 the app
        raise HTTPException(502, f"answer provider error: {e}")
    return {"question": body.q, **result}
