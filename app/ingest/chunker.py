from __future__ import annotations
from typing import Callable
from app.models import ParsedDoc, Chunk

MAX_TOKENS = 450
OVERLAP_TOKENS = 40
TokenCounter = Callable[[str], int]


def make_token_counter(settings) -> TokenCounter:
    try:
        from tokenizers import Tokenizer
        import os
        path = os.path.join(settings.embed_model_path or "", "tokenizer.json")
        if settings.embed_model_path and os.path.exists(path):
            tok = Tokenizer.from_file(path)
            return lambda t: len(tok.encode(t).ids)
    except Exception:
        pass
    # fallback estimate: wordpiece ~1.6x whitespace words
    return lambda t: int(len(t.split()) * 1.6) + 1


def _header(title: str, heading: str | None) -> str:
    return f"[{title} — {heading}]\n" if heading else f"[{title}]\n"


def _split_words(words: list[str], budget: int, overlap: int, count) -> list[str]:
    out, i = [], 0
    while i < len(words):
        j = i
        while j < len(words) and count(" ".join(words[i:j + 1])) <= budget:
            j += 1
        j = max(j, i + 1)
        out.append(" ".join(words[i:j]))
        if j >= len(words):
            break
        i = max(j - overlap, i + 1)
    return out


def chunk_document(parsed: ParsedDoc, document_id: int, title: str,
                   count_tokens: TokenCounter) -> list[Chunk]:
    chunks: list[Chunk] = []
    seq = 0
    for block in parsed.text_blocks:
        header = _header(title, block.heading)
        budget = MAX_TOKENS - count_tokens(header)
        if block.kind == "table":
            lines = block.text.splitlines()
            head_row, body = (lines[0], lines[1:]) if lines else ("", [])
            group: list[str] = []

            def flush(group):
                nonlocal seq
                if not group:
                    return
                raw = head_row + "\n" + "\n".join(group)
                chunks.append(Chunk(document_id, seq, raw, header + raw, block.location))
                seq += 1

            for row in body:
                trial = head_row + "\n" + "\n".join(group + [row])
                if count_tokens(header + trial) > MAX_TOKENS and group:
                    flush(group); group = [row]
                else:
                    group.append(row)
            flush(group)
        else:
            for piece in _split_words(block.text.split(), budget, OVERLAP_TOKENS, count_tokens):
                chunks.append(Chunk(document_id, seq, piece, header + piece, block.location))
                seq += 1
    return chunks
