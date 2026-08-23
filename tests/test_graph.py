from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def _client(tmp_path):
    return TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                                 embedder=FakeEmbedder(dim=384)))


def test_documents_link_through_shared_entities(tmp_path):
    with _client(tmp_path) as c:
        # two docs that share the same vendor + email
        c.post("/documents/text", json={"title": "Inv A",
               "text": "Vendor: Acme Corp\nTotal Rs.100. billing@acme.com"})
        c.post("/documents/text", json={"title": "Inv B",
               "text": "Vendor: Acme Corp\nTotal Rs.200. billing@acme.com"})
        g = c.get("/graph").json()
        kinds = [n["data"]["kind"] for n in g["nodes"]]
        assert kinds.count("doc") == 2
        assert "entity" in kinds
        # a shared entity (Acme Corp / the email) connects to both documents
        shared = [n for n in g["nodes"] if n["data"]["kind"] == "entity" and n["data"].get("shared")]
        assert shared, "expected at least one entity shared across documents"
        assert g["counts"]["shared"] >= 1


def test_query_highlights_matching_entity(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "Inv", "text": "Vendor: Acme Corp\nbilling@acme.com"})
        g = c.get("/graph", params={"q": "acme"}).json()
        assert any(n["data"].get("matched") for n in g["nodes"] if n["data"]["kind"] == "entity")


def test_empty_graph(tmp_path):
    with _client(tmp_path) as c:
        g = c.get("/graph").json()
        assert g["nodes"] == [] and g["edges"] == []
