"""Optional grounded-answer (RAG generation) layer.

The retrieval half is LLM-free; this is the thin, swappable generation stage that
plugs into the /answer seam. Provider-agnostic over any OpenAI-compatible chat API
(Groq free tier, OpenAI, Together, or local Ollama), configured entirely by env vars.
Answers are grounded strictly in retrieved excerpts and cite their sources.
"""
from __future__ import annotations
import json
import urllib.request
from typing import Protocol

SYSTEM_PROMPT = (
    "You are EasyNotes' answer assistant. Answer the user's question using ONLY the "
    "document excerpts provided. Cite the documents you used inline as [Title]. "
    "If the excerpts do not contain the answer, say exactly: "
    "\"I couldn't find that in your documents.\" Be concise and factual."
)


class Synthesizer(Protocol):
    def answer(self, question: str, hits: list) -> dict: ...


def _context(hits) -> str:
    parts = []
    for h in hits:
        loc = f" ({h.location})" if h.location else ""
        parts.append(f"[{h.document_title}{loc}]\n{h.text}")
    return "\n\n".join(parts)


def _citations(hits) -> list[dict]:
    seen, out = set(), []
    for h in hits:
        if h.document_id in seen:
            continue
        seen.add(h.document_id)
        out.append({"document_id": h.document_id, "document_title": h.document_title,
                    "location": h.location})
    return out


class OpenAICompatSynthesizer:
    """Works with any OpenAI-compatible /chat/completions endpoint."""
    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: int = 60):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def answer(self, question: str, hits: list) -> dict:
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Excerpts:\n{_context(hits)}\n\nQuestion: {question}"},
            ],
        }
        # A real User-Agent is required: some providers front their API with Cloudflare,
        # which 403-blocks the default "Python-urllib" agent as a bot.
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "EasyNotes/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"].strip()
        return {"answer": text, "citations": _citations(hits)}


class FakeSynthesizer:
    """Deterministic, network-free synthesizer for tests."""
    def answer(self, question: str, hits: list) -> dict:
        titles = ", ".join(f"[{h.document_title}]" for h in hits[:3])
        return {"answer": f"Based on {titles}: {question}", "citations": _citations(hits)}


def make_synthesizer(settings):
    """Return a synthesizer if configured, else None (=> /answer stays a 501 slot)."""
    if settings.answer_model and (settings.answer_api_key or settings.answer_base_url):
        return OpenAICompatSynthesizer(
            settings.answer_base_url or "https://api.openai.com/v1",
            settings.answer_api_key, settings.answer_model)
    return None
