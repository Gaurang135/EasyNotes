from __future__ import annotations
import urllib.error
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.models import SearchFilter
from app.search.service import run_search, detect_aggregate_intent, structured_context
from app.answer import reconcile_listed_total
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
    # Aggregate questions ("how many", "list all", "distinct") can't be answered from a
    # top-k retrieval sample — the model would silently miss documents. For these we hand
    # it the COMPLETE library listing (every doc + every extracted field) so counts and
    # distinct lists are computed over all the data; excerpts still ride along for detail.
    aggregate = detect_aggregate_intent(body.q)
    extra = structured_context(state.conn, body.q) if aggregate else ""
    hits = run_search(state.conn, state.embedder, state.vector_index, state.fts_index,
                      query=body.q, mode=body.mode, flt=SearchFilter(), limit=10, offset=0)
    if not hits and not extra:
        return {"question": body.q, "answer": "I couldn't find anything relevant in your documents.",
                "citations": []}
    try:
        result = synth.answer(body.q, hits, extra_context=extra)
    except urllib.error.HTTPError as e:
        # rate limit (429) or provider overload (5xx) that survived retries — degrade
        # gracefully to a "busy, try again" card instead of a hard error
        if e.code in (429, 500, 502, 503, 504):
            return {"question": body.q, "aggregate": aggregate,
                    "answer": "The answer model is busy right now. Please try again in a few "
                              "seconds — search and the Data views still work instantly.",
                    "citations": [], "rate_limited": True}
        raise HTTPException(502, f"answer provider error: {e}")
    except Exception as e:                        # provider/network errors never 500 the app
        raise HTTPException(502, f"answer provider error: {e}")
    # Never let a model arithmetic slip reach the user: recompute any itemized total in code.
    result["answer"] = reconcile_listed_total(result.get("answer", ""))
    return {"question": body.q, "aggregate": aggregate, **result}
