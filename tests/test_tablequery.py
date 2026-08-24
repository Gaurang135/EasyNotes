"""Unit tests for the FastAPI-free table query engine (Mode A: precise/defined queries)."""
from app.search.tablequery import query_table

COLS = [{"name": "vendor", "type": "text"}, {"name": "amount", "type": "number"}]
ROWS = [["Acme", "1200"], ["Globex", "300"], ["Acme", "4500"]]


def test_number_gte_filter():
    r = query_table(COLS, ROWS, col="amount", op="gte", val="1000")
    assert r["total"] == 2 and ["Globex", "300"] not in r["rows"]


def test_number_lte_filter():
    r = query_table(COLS, ROWS, col="amount", op="lte", val="1000")
    assert r["total"] == 1 and r["rows"] == [["Globex", "300"]]


def test_text_contains_filter_is_case_insensitive():
    r = query_table(COLS, ROWS, col="vendor", op="contains", val="acme")
    assert r["total"] == 2 and all(row[0] == "Acme" for row in r["rows"])


def test_sort_number_desc():
    r = query_table(COLS, ROWS, sort="amount", dir="desc")
    assert [row[1] for row in r["rows"]] == ["4500", "1200", "300"]


def test_pagination_reports_full_total():
    r = query_table(COLS, ROWS, sort="amount", dir="asc", limit=1, offset=1)
    assert r["total"] == 3 and len(r["rows"]) == 1 and r["rows"][0] == ["Acme", "1200"]


def test_unknown_column_is_ignored():
    r = query_table(COLS, ROWS, col="nope", val="x")
    assert r["total"] == 3            # bad column → no filtering, not an error


def test_non_numeric_cell_excluded_from_number_filter():
    rows = [["Acme", "n/a"], ["Globex", "500"]]
    r = query_table(COLS, rows, col="amount", op="gte", val="100")
    assert r["rows"] == [["Globex", "500"]]
