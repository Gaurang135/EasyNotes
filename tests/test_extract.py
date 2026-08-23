from app.ingest.extract import extract_fields, infer_column_type


def test_extracts_typed_fields():
    text = ("Invoice date: 2026-03-14. Total ₹1,299.50 due. "
            "Contact billing@acme.com or visit https://acme.com/pay")
    kinds = {f.kind for f in extract_fields(text)}
    assert {"email", "url", "amount", "date"} <= kinds
    vals = {f.value for f in extract_fields(text)}
    assert "billing@acme.com" in vals
    assert any("1,299.50" in v for v in vals)


def test_extracts_key_value_pairs():
    text = "Vendor: Acme Corp\nStatus: Paid\nRandom line without a pair"
    pairs = {f.key: f.value for f in extract_fields(text) if f.kind == "pair"}
    assert pairs.get("Vendor") == "Acme Corp"
    assert pairs.get("Status") == "Paid"


def test_deduplicates():
    text = "mail me at a@b.com or a@b.com again"
    emails = [f for f in extract_fields(text) if f.kind == "email"]
    assert len(emails) == 1


def test_empty_text_is_safe():
    assert extract_fields("") == []


def test_infer_column_type():
    assert infer_column_type(["1", "2", "3,000", "4.5"]) == "number"
    assert infer_column_type(["2026-01-01", "2025-12-31"]) == "date"
    assert infer_column_type(["alpha", "bravo"]) == "text"
    assert infer_column_type([]) == "text"
