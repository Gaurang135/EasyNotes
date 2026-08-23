from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def _client(tmp_path):
    # dim=384 matches the vec0 table so the sqlite-vec path accepts the vectors
    app = create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                     embedder=FakeEmbedder(dim=384))
    return TestClient(app)


def test_upload_then_search_all_modes(tmp_path):
    with _client(tmp_path) as c:
        up = c.post("/documents", files={"file": ("note.txt", b"refund policy for late payments", "text/plain")})
        assert up.status_code == 201
        doc_id = up.json()["id"]
        # background task runs synchronously under TestClient
        assert c.get(f"/documents/{doc_id}").json()["status"] == "ready"
        for mode in ("keyword", "semantic", "hybrid"):
            r = c.get("/search", params={"q": "refund", "mode": mode})
            assert r.status_code == 200
            hits = r.json()["results"]
            assert any(h["document_id"] == doc_id for h in hits), mode


def test_paste_text_and_delete(tmp_path):
    with _client(tmp_path) as c:
        up = c.post("/documents/text", json={"title": "Memo", "text": "quarterly revenue was strong"})
        doc_id = up.json()["id"]
        assert c.get("/search", params={"q": "revenue"}).json()["results"]
        assert c.delete(f"/documents/{doc_id}").status_code == 204
        assert c.get("/search", params={"q": "revenue"}).json()["results"] == []
