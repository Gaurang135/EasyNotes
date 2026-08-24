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


def test_extracts_invoice_line_items():
    # product names hide in the messy "Line items" run; qty + amount ride along
    text = ("INVOICE #INV-2000 Vendor: Acme Corp Line items: Cog x8 Rs.557.17 "
            "Gadget x18 Rs.278.75 Panel x2 Rs.161.11 Subtotal Rs.2324,000.00 "
            "Tax Rs.418,000.00 Total Rs.2742,000.00")
    items = [f for f in extract_fields(text) if f.kind == "item"]
    names = {f.key for f in items}
    assert {"Cog", "Gadget", "Panel"} <= names
    # the item carries its quantity and price so it is queryable, not just a name
    cog = next(f for f in items if f.key == "Cog")
    assert "8" in cog.value and "557.17" in cog.value
    # Subtotal / Tax / Total are NOT line items (no quantity) — must not be mistaken for products
    assert "Subtotal" not in names and "Total" not in names and "Tax" not in names


def test_line_items_ignored_without_quantity():
    # a bare "Label Rs.X" (no 'xN') is a total, not a purchased item
    text = "Total Rs.1,533.50 due. Balance Rs.0.00"
    assert [f for f in extract_fields(text) if f.kind == "item"] == []


def test_deduplicates():
    text = "mail me at a@b.com or a@b.com again"
    emails = [f for f in extract_fields(text) if f.kind == "email"]
    assert len(emails) == 1


def test_pair_ignores_diagram_and_code_lines():
    # Mermaid arrows / code must NOT become key:value pairs (the reported accuracy bug:
    # the hyphen separator turned "A --> B" into key="A ", value="> B")
    text = ("BR -|> RC & RP & RO\n"
            "APR -|\"Revise\" --> BR\n"
            "RC --> DB\n"
            "A -- yes --> B\n"
            "x := y\n"
            "return total - 1")
    assert [f for f in extract_fields(text) if f.kind == "pair"] == []


def test_pair_ignores_mermaid_style_and_fenced_code():
    # diagram directives ("style X fill:…"), diagram headers, and fenced code blocks
    # must not yield pairs — only the real key:value outside them survives
    text = ("flowchart TD\n"
            "style PHASE1 fill:#eff6ff,stroke:#3b82f6\n"
            "```\nsecret: do-not-extract\n```\n"
            "Vendor: Acme Corp")
    pairs = {f.key: f.value for f in extract_fields(text) if f.kind == "pair"}
    assert pairs == {"Vendor": "Acme Corp"}


def test_pair_rejects_noise_values():
    # a colon line whose value is punctuation/arrows carries no real fact
    text = "Arrow: -->\nJunk: |{}[]\nEmpty: &&&"
    assert [f for f in extract_fields(text) if f.kind == "pair"] == []


def test_pair_still_extracts_real_colon_pairs():
    text = "Vendor: Acme Corp\nStatus: Paid\nInvoice No: INV-2032"
    pairs = {f.key: f.value for f in extract_fields(text) if f.kind == "pair"}
    assert pairs.get("Vendor") == "Acme Corp"
    assert pairs.get("Status") == "Paid"
    assert pairs.get("Invoice No") == "INV-2032"      # hyphen inside a value is fine


def test_empty_text_is_safe():
    assert extract_fields("") == []


def test_infer_column_type():
    assert infer_column_type(["1", "2", "3,000", "4.5"]) == "number"
    assert infer_column_type(["2026-01-01", "2025-12-31"]) == "date"
    assert infer_column_type(["alpha", "bravo"]) == "text"
    assert infer_column_type([]) == "text"
