"""Failure-path tests. Each asserts a specific graceful behavior so a future change
that breaks it is caught here, not in production."""
from pathlib import Path
import zipfile
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def _client(tmp_path, **over):
    over["DATA_DIR"] = str(tmp_path)
    return TestClient(create_app(Settings.from_env(overrides=over), embedder=FakeEmbedder(dim=384)))


def test_unsupported_file_type_returns_415(tmp_path):
    with _client(tmp_path) as c:
        r = c.post("/documents", files={"file": ("evil.exe", b"MZ\x00\x00", "application/octet-stream")})
        assert r.status_code == 415


def test_oversized_upload_returns_413(tmp_path):
    with _client(tmp_path, MAX_UPLOAD_MB="0") as c:   # 0 MB cap -> any non-empty file is too big
        r = c.post("/documents", files={"file": ("big.txt", b"hello world", "text/plain")})
        assert r.status_code == 413


def test_renamed_zip_as_docx_rejected(tmp_path):
    fake = tmp_path / "fake.docx"
    with zipfile.ZipFile(fake, "w") as z:
        z.writestr("junk.txt", "not a real docx")
    with _client(tmp_path) as c:
        r = c.post("/documents", files={"file": ("fake.docx", fake.read_bytes(),
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        assert r.status_code == 415   # sniffed as zip, not docx -> unsupported


def test_encrypted_pdf_fails_gracefully_with_reason(tmp_path):
    data = Path("tests/fixtures/user_locked.pdf").read_bytes()
    with _client(tmp_path) as c:
        doc_id = c.post("/documents", files={"file": ("locked.pdf", data, "application/pdf")}).json()["id"]
        d = c.get(f"/documents/{doc_id}").json()
        assert d["status"] == "failed"
        assert "password" in (d["error"] or "").lower()   # typed error mapped to reason


def test_empty_file_fails_with_reason(tmp_path):
    with _client(tmp_path) as c:
        doc_id = c.post("/documents", files={"file": ("empty.txt", b"   ", "text/plain")}).json()["id"]
        assert c.get(f"/documents/{doc_id}").json()["status"] == "failed"


def test_duplicate_upload_is_deduped(tmp_path):
    with _client(tmp_path) as c:
        body = b"the same content twice"
        r1 = c.post("/documents", files={"file": ("a.txt", body, "text/plain")})
        r2 = c.post("/documents", files={"file": ("a.txt", body, "text/plain")})
        assert r1.status_code == 201                       # created
        assert r2.status_code == 200                       # nothing created → not 201
        assert r2.json()["status"] == "duplicate" and r2.json()["id"] == r1.json()["id"]


def test_bad_fts_query_does_not_500(tmp_path):
    with _client(tmp_path) as c:
        c.post("/documents/text", json={"title": "T", "text": "state-of-the-art c++ systems"})
        for q in ['"unbalanced', "c++", "NOT AND OR", "state-of-the-art", "colon:term"]:
            r = c.get("/search", params={"q": q, "mode": "keyword"})
            assert r.status_code == 200, q


def test_missing_document_returns_404(tmp_path):
    with _client(tmp_path) as c:
        assert c.get("/documents/9999").status_code == 404


def test_delete_removes_from_search(tmp_path):
    with _client(tmp_path) as c:
        doc_id = c.post("/documents/text", json={"title": "Del", "text": "unique_marker_xyz payload"}).json()["id"]
        assert c.get("/search", params={"q": "unique_marker_xyz"}).json()["results"]
        c.delete(f"/documents/{doc_id}")
        assert c.get("/search", params={"q": "unique_marker_xyz"}).json()["results"] == []


def test_search_with_empty_corpus_is_empty_not_error(tmp_path):
    with _client(tmp_path) as c:
        r = c.get("/search", params={"q": "anything"})
        assert r.status_code == 200 and r.json()["results"] == []
