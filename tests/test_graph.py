from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def _client(tmp_path):
    return TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                                 embedder=FakeEmbedder(dim=384)))


def test_documents_link_through_shared_entities(tmp_path):
    with _client(tmp_path) as c:
        # two docs that share the same vendor + email; one unrelated doc
        c.post("/documents/text", json={"title": "Inv A",
               "text": "Vendor: Acme Corp\nTotal Rs.100. billing@acme.com"})
        c.post("/documents/text", json={"title": "Inv B",
               "text": "Vendor: Acme Corp\nTotal Rs.200. billing@acme.com"})
        c.post("/documents/text", json={"title": "Loner", "text": "unrelated prose, no shared values"})
        g = c.get("/graph").json()
        # only shared entities appear (no single-doc leaf clutter)
        for n in g["nodes"]:
            if n["data"]["kind"] == "entity":
                assert n["data"]["docs"] >= 2
        assert g["counts"]["shared_entities"] >= 1
        assert g["counts"]["connected"] == 2 and g["counts"]["isolated"] == 1
        # readable summary lists the shared value and the docs it links
        assert any(conn["count"] >= 2 and set(["Inv A", "Inv B"]) <= set(conn["documents"])
                   for conn in g["connections"])


def test_query_highlights_matching_entity(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "Inv1", "text": "Invoice 1. Vendor: Acme Corp\nbilling@acme.com"})
        c.post("/documents/text", json={"title": "Inv2", "text": "Invoice 2. Vendor: Acme Corp\nbilling@acme.com"})
        g = c.get("/graph", params={"q": "acme"}).json()
        assert any(n["data"].get("matched") for n in g["nodes"] if n["data"]["kind"] == "entity")


def test_empty_graph(tmp_path):
    with _client(tmp_path) as c:
        g = c.get("/graph").json()
        assert g["nodes"] == [] and g["edges"] == [] and g["connections"] == []
