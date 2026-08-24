from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder
from app.answer import FakeSynthesizer


def _settings(tmp_path):
    return Settings.from_env(overrides={"DATA_DIR": str(tmp_path)})


def test_answer_returns_501_when_llm_disabled(tmp_path):
    with TestClient(create_app(_settings(tmp_path), embedder=FakeEmbedder(dim=16))) as c:
        r = c.post("/answer", json={"q": "anything"})
        assert r.status_code == 501
        assert "LLM" in r.json()["detail"]


def test_answer_is_grounded_with_citations_when_enabled(tmp_path):
    app = create_app(_settings(tmp_path), embedder=FakeEmbedder(dim=384),
                     answer_synth=FakeSynthesizer())
    with TestClient(app) as c:
        c.post("/documents/text", json={"title": "Refund Policy",
               "text": "Customers may request a refund within 30 days of purchase."})
        r = c.post("/answer", json={"q": "what is the refund window?"})
        assert r.status_code == 200
        body = r.json()
        assert body["answer"]
        assert any(cit["document_title"] == "Refund Policy" for cit in body["citations"])


def test_answer_handles_empty_corpus(tmp_path):
    app = create_app(_settings(tmp_path), embedder=FakeEmbedder(dim=384),
                     answer_synth=FakeSynthesizer())
    with TestClient(app) as c:
        r = c.post("/answer", json={"q": "anything"})
        assert r.status_code == 200 and r.json()["citations"] == []
