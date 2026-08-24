from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def _client(tmp_path):
    return TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                                 embedder=FakeEmbedder(dim=384)))


CSV = ("region,amount,date\n"
       "north,1200,2026-01-05\n"
       "south,300,2026-02-11\n"
       "east,4500,2026-03-02\n")


def _upload_csv(c, name="sales.csv"):
    return c.post("/documents", files={"file": (name, CSV.encode(), "text/csv")})


def test_csv_becomes_a_typed_queryable_table(tmp_path):
    with _client(tmp_path) as c:
        _upload_csv(c)
        tables = c.get("/tables").json()
        assert len(tables) == 1
        cols = {col["name"]: col["type"] for col in tables[0]["columns"]}
        assert cols["amount"] == "number"      # type inference
        assert cols["date"] == "date"
        assert tables[0]["row_count"] == 3


def test_numeric_filter_and_sort(tmp_path):
    with _client(tmp_path) as c:
        _upload_csv(c)
        tid = c.get("/tables").json()[0]["id"]
        # numeric >= 1000 should drop the 300 row
        r = c.get(f"/tables/{tid}/rows", params={"col": "amount", "op": "gte", "val": "1000"}).json()
        assert r["total"] == 2
        amounts = [float(row[1]) for row in r["rows"]]
        assert min(amounts) >= 1000
        # sort desc by amount
        s = c.get(f"/tables/{tid}/rows", params={"sort": "amount", "dir": "desc"}).json()
        ordered = [float(row[1]) for row in s["rows"]]
        assert ordered == sorted(ordered, reverse=True)


def test_text_contains_filter(tmp_path):
    with _client(tmp_path) as c:
        _upload_csv(c)
        tid = c.get("/tables").json()[0]["id"]
        r = c.get(f"/tables/{tid}/rows", params={"col": "region", "op": "contains", "val": "sou"}).json()
        assert r["total"] == 1 and r["rows"][0][0] == "south"


def test_fields_extracted_from_text(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "Invoice",
               "text": "Vendor: Acme\nTotal ₹1,299.50 due on 2026-03-14. billing@acme.com"})
        fields = c.get("/fields").json()
        kinds = {f["kind"] for f in fields}
        assert {"email", "amount", "date", "pair"} <= kinds
        emails = c.get("/fields", params={"kind": "email"}).json()
        assert emails and emails[0]["value"] == "billing@acme.com"


def test_stats_reflects_corpus(tmp_path):
    with _client(tmp_path) as c:
        _upload_csv(c)
        s = c.get("/stats").json()
        assert s["documents"] == 1 and s["tables"] == 1 and s["by_type"].get("csv") == 1


def test_delete_removes_structured_data(tmp_path):
    with _client(tmp_path) as c:
        up = _upload_csv(c).json()
        assert c.get("/tables").json()
        c.delete(f"/documents/{up['id']}")
        assert c.get("/tables").json() == []
        assert c.get("/fields").json() == []


# ---- error scenarios (must catch faulty future changes) ----
def test_query_missing_table_404(tmp_path):
    with _client(tmp_path) as c:
        assert c.get("/tables/999/rows").status_code == 404


def test_unknown_filter_column_is_ignored_not_500(tmp_path):
    with _client(tmp_path) as c:
        _upload_csv(c)
        tid = c.get("/tables").json()[0]["id"]
        r = c.get(f"/tables/{tid}/rows", params={"col": "nope", "val": "x"})
        assert r.status_code == 200 and r.json()["total"] == 3   # bad column ignored


def test_insights_computes_exact_spend_analytics(tmp_path):
    # two invoice-like notes with amounts + a vendor pair -> deterministic spend insights
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "inv1",
               "text": "Vendor: Acme\nInvoice date: 2026-01-10\nTotal Rs.100.50"})
        c.post("/documents/text", json={"title": "inv2",
               "text": "Vendor: Globex\nInvoice date: 2026-02-20\nTotal Rs.200.00"})
        d = c.get("/insights").json()
        assert d["documents"] == 2
        assert d["amount"]["total"] == 300.5          # exact sum, no AI
        assert d["amount"]["max"] == 200.0
        assert d["distinct_vendors"] == 2
        names = {v["name"] for v in d["by_vendor"]}
        assert {"Acme", "Globex"} <= names
        assert d["date_range"]["min"] == "2026-01-10"


def test_seed_populates_empty_corpus_then_refuses(tmp_path):
    with _client(tmp_path) as c:
        assert c.get("/documents").json() == []
        r = c.post("/documents/seed")
        assert r.status_code == 200 and r.json()["added"] >= 4   # bundled samples ingested
        assert len(c.get("/documents").json()) >= 4
        # seed only runs on an empty corpus
        assert c.post("/documents/seed").status_code == 409
