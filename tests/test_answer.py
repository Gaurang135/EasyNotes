from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def test_answer_returns_501_with_instructions(tmp_path):
    with TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                               embedder=FakeEmbedder(dim=16))) as c:
        r = c.post("/answer", json={"q": "anything"})
        assert r.status_code == 501
        assert "LLM" in r.json()["detail"]
