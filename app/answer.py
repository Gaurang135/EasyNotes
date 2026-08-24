"""Optional grounded-answer (RAG generation) layer.

The retrieval half is LLM-free; this is the thin, swappable generation stage that
plugs into the /answer seam. Provider-agnostic over any OpenAI-compatible chat API
(Groq free tier, OpenAI, Together, or local Ollama), configured entirely by env vars.
Answers are grounded strictly in retrieved excerpts and cite their sources.
"""
from __future__ import annotations
import json
import time
import urllib.request
import urllib.error
from typing import Protocol

SYSTEM_PROMPT = (
    "You are EasyNotes' answer assistant. Answer the user's question using ONLY the "
    "document excerpts provided.\n"
    "FORMAT RULES:\n"
    "- Lead with a one-line direct answer.\n"
    "- When the answer is a list of items/entities, output a Markdown bullet list with "
    "EXACTLY ONE item per line. Never put multiple items in a comma-separated sentence, "
    "and never repeat the list as a trailing summary sentence.\n"
    "- Each bullet: the item in **bold**, then its key detail (quantity/amount/etc.), then "
    "the source in brackets as [Title]. The source is a reference, not the answer.\n"
    "COUNTING & LISTING: if a 'CORPUS INVENTORY' block is provided, it is the COMPLETE set of "
    "documents (one per line as 'title [type] :: fields') and is the whole corpus — count and "
    "list from it exhaustively, give the exact total, and cite each item with its document "
    "title in brackets, e.g. [invoice_07]. Judge membership by meaning, not by title pattern "
    "(a document titled 'Acme Invoice' is an invoice too); do not stop early. If only excerpts "
    "are provided, they are the top matches (not the whole corpus): answer from them and say "
    "counts are 'at least N in the retrieved excerpts'.\n"
    "If neither the inventory nor the excerpts contain the answer, say exactly: "
    "\"I couldn't find that in your documents.\" Be concise; never invent details."
)


class Synthesizer(Protocol):
    def answer(self, question: str, hits: list, extra_context: str = "") -> dict: ...


def _retry_after(err, attempt: int) -> float:
    """Seconds to wait before retrying a 429 — honour Retry-After if sent, else backoff."""
    hdr = err.headers.get("Retry-After") if getattr(err, "headers", None) else None
    if hdr:
        try:
            return min(float(hdr), 10.0)
        except ValueError:
            pass
    return min(2 ** attempt, 8.0)


def _context(hits, max_chars_each: int = 1200) -> str:
    parts = []
    for h in hits:
        loc = f" ({h.location})" if h.location else ""
        text = h.text if len(h.text) <= max_chars_each else h.text[:max_chars_each] + "…"
        parts.append(f"[{h.document_title}{loc}]\n{text}")
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

    def answer(self, question: str, hits: list, extra_context: str = "") -> dict:
        # Providers cap request size (Groq's free tier returns 413). Try the richest
        # payload first, then progressively shrink excerpts, then the inventory, so a big
        # corpus still gets an answer instead of erroring. The inventory is trimmed last
        # and from the end, where the least-critical fields sit (see structured_context).
        variants = [
            (extra_context, hits, 1200),
            (extra_context, hits[:3], 500),
            (extra_context, [], 0),
            (extra_context[:6000], [], 0),
        ]
        last_err: Exception | None = None
        for ctx, hs, cap in variants:
            try:
                text = self._chat(question, hs, ctx, cap)
                return {"answer": text, "citations": _citations(hs or hits)}
            except urllib.error.HTTPError as e:
                if e.code == 413:            # too large — shrink and retry
                    last_err = e
                    continue
                raise
        raise last_err  # every variant was still too large

    def _chat(self, question: str, hits: list, extra_context: str, cap: int) -> str:
        user = ""
        if extra_context:
            user += ("Use this COMPLETE corpus inventory for any counting/listing/distinct "
                     "question (it is the whole corpus, not a sample):\n" + extra_context + "\n\n")
        if hits:
            user += f"Excerpts (for detail/quotes):\n{_context(hits, cap)}\n\n"
        user += f"Question: {question}"
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        }
        # A real User-Agent is required: some providers front their API with Cloudflare,
        # which 403-blocks the default "Python-urllib" agent as a bot.
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "EasyNotes/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=headers)
        # Retry transient failures — 429 (free-tier rate limit) and dropped TLS connections —
        # with a short backoff. 413 is NOT retried here; it bubbles up so answer() can shrink.
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"].strip()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(_retry_after(e, attempt))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                raise urllib.error.URLError(f"answer provider unreachable: {e}")


class FakeSynthesizer:
    """Deterministic, network-free synthesizer for tests."""
    def answer(self, question: str, hits: list, extra_context: str = "") -> dict:
        titles = ", ".join(f"[{h.document_title}]" for h in hits[:3])
        prefix = "[corpus] " if extra_context else ""
        return {"answer": f"{prefix}Based on {titles}: {question}", "citations": _citations(hits)}


def make_synthesizer(settings):
    """Return a synthesizer if configured, else None (=> /answer stays a 501 slot)."""
    if settings.answer_model and (settings.answer_api_key or settings.answer_base_url):
        return OpenAICompatSynthesizer(
            settings.answer_base_url or "https://api.openai.com/v1",
            settings.answer_api_key, settings.answer_model)
    return None
