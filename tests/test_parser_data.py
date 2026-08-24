import json
import pytest
from app.ingest.parsers.json import JsonParser
from app.ingest.parsers.html import HtmlParser
from app.errors import CorruptFileError, EmptyDocumentError


# ---------- JSON ----------

def test_json_array_of_records_becomes_table(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps([
        {"vendor": "Acme", "amount": 10, "city": "NYC"},
        {"vendor": "Globex", "amount": 20, "city": "LA"}]))
    t = JsonParser().parse(p).tables[0]
    assert set(t.columns) == {"vendor", "amount", "city"}
    assert len(t.rows) == 2


def test_json_nested_object_flattens_to_searchable_fields(tmp_path):
    p = tmp_path / "o.json"
    p.write_text(json.dumps({
        "invoice": "INV-1", "total": 1299.5,
        "contact": {"email": "billing@acme.com", "phone": "+91 90000 00000"},
        "tags": ["urgent", "paid"]}))
    text = "\n".join(b.text for b in JsonParser().parse(p).text_blocks)
    assert "contact.email: billing@acme.com" in text     # nested keys flattened with dot paths
    assert "1299.5" in text                               # numbers preserved for field extraction
    assert "urgent, paid" in text                         # scalar arrays joined


def test_json_complex_nested_records_and_meta(tmp_path):
    # an object holding both metadata AND a nested array of records
    p = tmp_path / "c.json"
    p.write_text(json.dumps({
        "meta": {"generated": "2026-01-01", "owner": "Ada"},
        "orders": [{"id": 1, "item": "Cog", "price": 5},
                   {"id": 2, "item": "Bolt", "price": 7}]}))
    doc = JsonParser().parse(p)
    orders = next(t for t in doc.tables if t.name == "orders")
    assert len(orders.rows) == 2 and "item" in orders.columns
    text = "\n".join(b.text for b in doc.text_blocks)
    assert "meta.owner: Ada" in text                      # sibling metadata still captured


def test_json_deeply_nested_object_in_cell_is_preserved(tmp_path):
    # a record whose value is itself an object — must not be dropped
    p = tmp_path / "d.json"
    p.write_text(json.dumps([{"id": 1, "addr": {"city": "NYC", "zip": "10001"}}]))
    t = JsonParser().parse(p).tables[0]
    joined = "\t".join(t.rows[0])
    assert "NYC" in joined and "10001" in joined


def test_json_invalid_raises_corrupt(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json,,,}")
    with pytest.raises(CorruptFileError):
        JsonParser().parse(p)


def test_json_empty_raises(tmp_path):
    p = tmp_path / "e.json"
    p.write_text("   ")
    with pytest.raises(EmptyDocumentError):
        JsonParser().parse(p)


# ---------- HTML ----------

def test_html_extracts_text_and_strips_scripts(tmp_path):
    p = tmp_path / "a.html"
    p.write_text("<html><head><title>Report Q1</title><style>.x{color:red}</style></head>"
                 "<body><h1>Revenue</h1><p>Strong quarter.</p><script>steal()</script></body></html>")
    text = "\n".join(b.text for b in HtmlParser().parse(p).text_blocks)
    assert "Revenue" in text and "Strong quarter" in text
    assert "steal" not in text and "color:red" not in text   # script/style removed


def test_html_table_becomes_structured_table(tmp_path):
    p = tmp_path / "t.html"
    p.write_text("<table><tr><th>Vendor</th><th>Amount</th></tr>"
                 "<tr><td>Acme</td><td>10</td></tr><tr><td>Globex</td><td>20</td></tr></table>")
    t = HtmlParser().parse(p).tables[0]
    assert t.columns == ["Vendor", "Amount"]
    assert ["Acme", "10"] in t.rows and len(t.rows) == 2


def test_html_nested_table_does_not_crash_and_keeps_content(tmp_path):
    p = tmp_path / "n.html"
    p.write_text("<table><tr><td>Parent<table><tr><td>child1</td><td>child2</td></tr></table></td>"
                 "<td>B</td></tr></table>")
    doc = HtmlParser().parse(p)                            # nested tables must not crash extraction
    assert any("child1" in b.text for b in doc.text_blocks)


def test_html_empty_raises(tmp_path):
    p = tmp_path / "e.html"
    p.write_text("")
    with pytest.raises(EmptyDocumentError):
        HtmlParser().parse(p)
