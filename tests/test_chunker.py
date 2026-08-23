from app.models import ParsedDoc, TextBlock
from app.ingest.chunker import chunk_document, MAX_TOKENS


def _count(text):  # deterministic fake counter: 1 token per whitespace word
    return len(text.split())


def test_header_is_prepended_to_embed_text_only():
    parsed = ParsedDoc(text_blocks=[TextBlock(text="body text", kind="prose", heading="Intro")],
                       metadata={}, warnings=[])
    chunks = chunk_document(parsed, document_id=1, title="My Doc", count_tokens=_count)
    assert chunks[0].text == "body text"                      # raw preserved
    assert "My Doc" in chunks[0].embed_text                   # context in embed text
    assert "Intro" in chunks[0].embed_text


def test_every_chunk_under_token_budget():
    big = " ".join(f"word{i}" for i in range(5000))
    parsed = ParsedDoc(text_blocks=[TextBlock(text=big, kind="prose")], metadata={}, warnings=[])
    chunks = chunk_document(parsed, 1, "T", _count)
    assert len(chunks) > 1
    for c in chunks:
        assert _count(c.embed_text) <= MAX_TOKENS


def test_table_rows_split_by_budget_keep_header():
    rows = "\n".join(f"{i},{i*1000},TXN{i}" for i in range(400))
    block = TextBlock(text="id,amount,ref\n" + rows, kind="table", location="rows")
    parsed = ParsedDoc(text_blocks=[block], metadata={}, warnings=[])
    chunks = chunk_document(parsed, 1, "T", _count)
    for c in chunks:
        assert "id,amount,ref" in c.embed_text
        assert _count(c.embed_text) <= MAX_TOKENS
