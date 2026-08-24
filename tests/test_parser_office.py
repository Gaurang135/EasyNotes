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


def test_csv_with_header_uses_it(tmp_path):
    p = tmp_path / "h.csv"
    p.write_text("vendor,amount,date\nAcme,557.17,2026-01-01\nGlobex,42.00,2026-02-02\n")
    t = CsvParser().parse(p).tables[0]
    assert t.columns == ["vendor", "amount", "date"]
    assert len(t.rows) == 2                      # header not counted as data


def test_csv_without_header_synthesizes_columns_and_keeps_all_rows(tmp_path):
    # no label row — every line is data (numbers/dates). The first row must NOT be
    # eaten as a header, or that record goes missing and becomes unqueryable.
    p = tmp_path / "nh.csv"
    p.write_text("Acme,557.17,2026-01-01\nGlobex,42.00,2026-02-02\nInitech,9.50,2026-03-03\n")
    t = CsvParser().parse(p).tables[0]
    assert len(t.rows) == 3                       # all three records preserved
    assert "Acme" not in t.columns                # first record is not mistaken for headers
    assert all(c.lower().startswith("column") for c in t.columns)
    assert ["Acme", "557.17", "2026-01-01"] in t.rows
