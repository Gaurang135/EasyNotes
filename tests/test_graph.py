from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def _client(tmp_path):
    # dim=384 matches the vec0 table; floor=-1 so cross-doc top-k neighbors always form
    # edges with the (non-semantic) fake embedder, making the test deterministic.
    app = create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path),
                                                   "EDGE_SIMILARITY_FLOOR": "-1"}),
                     embedder=FakeEmbedder(dim=384))
    return TestClient(app)


def test_graph_has_nodes_and_cross_doc_edges(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "A", "text": "refund policy for payments and chargebacks"})
        c.post("/documents/text", json={"title": "B", "text": "payment refund and chargeback handling"})
        g = c.get("/graph").json()
        assert len(g["nodes"]) >= 2
        for e in g["edges"]:
            assert e["data"]["source_doc"] != e["data"]["target_doc"]
        assert len(g["edges"]) >= 1


def test_graph_query_marks_matches(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "A", "text": "refund policy"})
        g = c.get("/graph", params={"q": "refund"}).json()
        assert any(n["data"].get("matched") for n in g["nodes"])


def test_graph_export_is_graphml(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "A", "text": "refund policy"})
        r = c.get("/graph/export")
        assert r.status_code == 200
        assert "graphml" in r.text
