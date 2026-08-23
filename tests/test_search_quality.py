"""Guards for retrieval UX quality: snippets center on meaningful terms, and
original files can be downloaded back."""
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder
from app.search.service import _snippet, content_terms

STORY = ("This polyester prison will only hold me for a little longer. "
         "I grab two fistfuls of my coat. The coat pops open. I'm free.")


def _client(tmp_path):
    return TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                                 embedder=FakeEmbedder(dim=384)))


def test_content_terms_drops_stopwords():
    assert content_terms("who is free") == ["free"]
    assert "is" not in content_terms("what is the total amount")


def test_snippet_anchors_on_meaningful_term_not_stopword():
    snip = _snippet(STORY, "who is free")
    assert "free" in snip.lower()          # centered on 'free', not the first 'is'


def test_download_returns_original_bytes(tmp_path):
    with _client(tmp_path) as c:
        body = b"downloadable original content"
        doc_id = c.post("/documents", files={"file": ("orig.txt", body, "text/plain")}).json()["id"]
        r = c.get(f"/documents/{doc_id}/download")
        assert r.status_code == 200
        assert r.content == body


def test_download_missing_is_404(tmp_path):
    with _client(tmp_path) as c:
        assert c.get("/documents/123/download").status_code == 404


def test_natural_language_query_finds_the_free_passage(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "Coat", "text": STORY})
        hits = c.get("/search", params={"q": "who is free", "mode": "hybrid"}).json()["results"]
        assert hits and "free" in hits[0]["snippet"].lower()
