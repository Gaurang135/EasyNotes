from pathlib import Path
from app.ingest.parsers.docx import DocxParser
from app.ingest.parsers.pptx import PptxParser
from app.ingest.parsers.xlsx import XlsxParser
from app.ingest.parsers.csv import CsvParser


def test_docx_preserves_order_and_headings():
    doc = DocxParser().parse(Path("tests/fixtures/sample.docx"))
    assert any(b.heading for b in doc.text_blocks)
    assert any(b.kind == "table" for b in doc.text_blocks)


def test_pptx_reads_titles_body_and_notes():
    doc = PptxParser().parse(Path("tests/fixtures/sample.pptx"))
    assert any(b.location and b.location.startswith("slide 1") for b in doc.text_blocks)
    joined = " ".join(b.text for b in doc.text_blocks)
    assert "notes" in joined.lower()


def test_xlsx_emits_table_block_with_sheet_location():
    doc = XlsxParser().parse(Path("tests/fixtures/sample.xlsx"))
    tb = doc.text_blocks[0]
    assert tb.kind == "table"
    assert tb.location and "Sheet" in tb.location


def test_csv_is_table_block():
    doc = CsvParser().parse(Path("tests/fixtures/wide.csv"))
    assert doc.text_blocks[0].kind == "table"
    assert "amount" in doc.text_blocks[0].text
