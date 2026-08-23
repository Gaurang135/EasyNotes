"""LLM-free query router: field-intent queries return extracted values directly."""
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder
from app.search.service import detect_field_intents


def _client(tmp_path):
    return TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                                 embedder=FakeEmbedder(dim=384)))


def test_intent_detection():
    assert "amount" in detect_field_intents("what is the total amount in invoices")
    assert "date" in detect_field_intents("when is it due")
    assert "email" in detect_field_intents("contact email please")
    assert detect_field_intents("tell me a story") == []


def test_total_amount_query_returns_amount_values(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "Invoice",
               "text": "Total Rs.1,299.50 due. Also a fee of Rs.234."})
        data = c.get("/search", params={"q": "total amount in invoices"}).json()
        vals = [a["value"] for a in data["answers"]]
        assert any("1,299.50" in v for v in vals)
        assert all(a["kind"] == "amount" for a in data["answers"])


def test_non_field_query_has_no_answers(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "Story", "text": "the coat pops open I am free"})
        data = c.get("/search", params={"q": "who is free"}).json()
        assert data["answers"] == []
