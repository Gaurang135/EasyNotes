import math
import pytest
from app import db
from app.search.vectors import NumpyVectorIndex, SqliteVecIndex


def _conn(tmp_path):
    conn = db.connect(str(tmp_path / "v.db"))
    db.init_schema(conn)
    _seed_chunks(conn, [1, 2, 3])
    return conn


def _seed_chunks(conn, ids):
    conn.execute("INSERT OR IGNORE INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at)"
                 " VALUES (1,'a','a','txt',1,'ready','h','2026')")
    for i in ids:
        conn.execute("INSERT OR IGNORE INTO chunks(id,document_id,seq,text,embed_text) VALUES (?,1,?,'x','x')",
                     (i, i))
    conn.commit()


def _make(name, conn):
    if name == "numpy":
        return NumpyVectorIndex(conn)
    if not getattr(conn, "vec_available", False):
        pytest.skip("sqlite-vec not available on this platform")
    return SqliteVecIndex(conn)


def _unit(x, y):
    n = math.hypot(x, y)
    return [x / n, y / n] + [0.0] * 382


@pytest.mark.parametrize("name", ["numpy", "sqlitevec"])
def test_identical_and_orthogonal_scores(tmp_path, name):
    conn = _conn(tmp_path)
    idx = _make(name, conn)
    idx.add([(1, _unit(1, 0)), (2, _unit(0, 1))])
    hits = {h.chunk_id: h.score for h in idx.search(_unit(1, 0), k=2)}
    assert hits[1] == pytest.approx(1.0, abs=1e-4)      # identical
    assert hits[2] == pytest.approx(0.0, abs=1e-4)      # orthogonal


@pytest.mark.parametrize("name", ["numpy", "sqlitevec"])
def test_ordering_best_first(tmp_path, name):
    conn = _conn(tmp_path)
    idx = _make(name, conn)
    idx.add([(1, _unit(1, 0)), (2, _unit(1, 1)), (3, _unit(0, 1))])
    order = [h.chunk_id for h in idx.search(_unit(1, 0), k=3)]
    assert order[0] == 1 and order[-1] == 3


@pytest.mark.parametrize("name", ["numpy", "sqlitevec"])
def test_churn_delete_then_reinsert(tmp_path, name):
    conn = _conn(tmp_path)
    idx = _make(name, conn)
    idx.add([(1, _unit(1, 0))])
    idx.delete_document(1)                 # removes chunk 1's vector
    _seed_chunks(conn, [4])
    idx.add([(4, _unit(0, 1))])
    ids = [h.chunk_id for h in idx.search(_unit(0, 1), k=5)]
    assert 1 not in ids and 4 in ids
