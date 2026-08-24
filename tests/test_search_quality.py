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


def test_search_finds_document_by_title_when_body_lacks_the_word(tmp_path):
    # people query by title/subject; the word need not appear in the body (e.g. a CSV of
    # rows that never says "sales"). Titles must be searchable, or the doc is unreachable.
    with _client(tmp_path) as c:
        c.post("/documents/text",
               json={"title": "Quarterly Sales", "text": "region,units,revenue\nWest,10,1000"})
        c.post("/documents/text",
               json={"title": "random", "text": "totally unrelated content about the weather"})
        hits = c.get("/search", params={"q": "sales", "mode": "hybrid"}).json()["results"]
        assert hits and any("Quarterly Sales" in h["document_title"] for h in hits[:3])


def test_search_title_matches_word_variant_by_prefix(tmp_path):
    # "specification" should reach a doc titled "spec_0" (spec↔specification)
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "spec_0", "text": "GET /sprocket owner Ava due 2026"})
        hits = c.get("/search", params={"q": "technical specification", "mode": "hybrid"}).json()["results"]
        assert hits and any("spec_0" in h["document_title"] for h in hits[:3])
