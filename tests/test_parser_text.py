from pathlib import Path
from app.ingest.parsers import PARSERS


def test_txt_parser_registered_and_parses():
    p = PARSERS["txt"]
    doc = p.parse(Path("tests/fixtures/hello.txt"))
    assert "payments" in doc.text_blocks[0].text


def test_md_parser_captures_heading():
    p = PARSERS["md"]
    doc = p.parse(Path("tests/fixtures/notes.md"))
    assert any(b.heading == "Title" for b in doc.text_blocks)
