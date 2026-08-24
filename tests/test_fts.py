import pytest
from app import db
from app.search.fts import Fts5Index, sanitize_fts_query
from app.models import SearchFilter


@pytest.mark.parametrize("raw", [
    "state-of-the-art", "c++", '"unbalanced', "cats NOT dogs",
    "^cats", "col:term", "?", "",
])
def test_sanitizer_never_raises_and_matches(tmp_path, raw):
    conn = db.connect(str(tmp_path / "f.db"))
    db.init_schema(conn)
    _seed(conn, "the state-of-the-art c++ approach beats cats")
    idx = Fts5Index(conn)
    # must not raise, regardless of input
    idx.search(sanitize_fts_query(raw), SearchFilter(), 10, 0)


def test_bm25_orders_denser_match_first(tmp_path):
    conn = db.connect(str(tmp_path / "f.db"))
    db.init_schema(conn)
    _seed(conn, "cat cat cat", chunk_id=1)
    _seed(conn, "cat dog", chunk_id=2, seq=1)
    idx = Fts5Index(conn)
    order = [h.chunk_id for h in idx.search(sanitize_fts_query("cat"), SearchFilter(), 10, 0)]
    assert order[0] == 1  # denser match ranks first; score higher-is-better
    hits = idx.search(sanitize_fts_query("cat"), SearchFilter(), 10, 0)
    assert hits[0].score >= hits[-1].score


def test_natural_language_query_matches_on_content_word(tmp_path):
    # "who is free" must still find a doc that says "free" — the stopwords who/is
    # must not force an AND that requires all three words in one chunk.
    conn = db.connect(str(tmp_path / "f.db"))
    db.init_schema(conn)
    _seed(conn, "Soon I will be free at last")
    idx = Fts5Index(conn)
    hits = idx.search(sanitize_fts_query("who is free"), SearchFilter(), 10, 0)
    assert len(hits) >= 1


def test_multi_term_query_is_or_not_strict_and(tmp_path):
    # a doc with only ONE of the content terms should still match (OR semantics)
    conn = db.connect(str(tmp_path / "f.db"))
    db.init_schema(conn)
    _seed(conn, "quarterly revenue report")
    idx = Fts5Index(conn)
    hits = idx.search(sanitize_fts_query("revenue and headcount projections"),
                      SearchFilter(), 10, 0)
    assert len(hits) >= 1


def _seed(conn, text, chunk_id=1, seq=0):
    conn.execute("INSERT OR IGNORE INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at)"
                 " VALUES (1,'a','a','txt',1,'ready','h','2026')")
    conn.execute("INSERT INTO chunks(id,document_id,seq,text,embed_text) VALUES (?,1,?,?,?)",
                 (chunk_id, seq, text, text))
    conn.commit()
