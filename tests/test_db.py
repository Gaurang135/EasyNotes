import sqlite3
from app import db
from app.models import Status


def _mk(tmp_path):
    conn = db.connect(str(tmp_path / "e.db"))
    db.init_schema(conn)
    return conn


def test_schema_creates_all_tables(tmp_path):
    conn = _mk(tmp_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"documents", "chunks", "chunks_fts", "tables", "table_rows", "fields", "meta"} <= names


def test_wal_enabled(tmp_path):
    conn = _mk(tmp_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_fts_trigger_syncs_on_insert(tmp_path):
    conn = _mk(tmp_path)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at) "
                 "VALUES (1,'a.txt','a','txt',3,'ready','h','2026-01-01')")
    conn.execute("INSERT INTO chunks(id,document_id,seq,text,embed_text) VALUES (1,1,0,'hello world','hello world')")
    conn.commit()
    rows = conn.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'hello'").fetchall()
    assert rows == [(1,)]


def test_delete_document_clears_all_tables(tmp_path):
    conn = _mk(tmp_path)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at) "
                 "VALUES (1,'a.txt','a','txt',3,'ready','h','2026-01-01')")
    conn.execute("INSERT INTO chunks(id,document_id,seq,text,embed_text) VALUES (1,1,0,'hello','hello')")
    conn.commit()
    db.delete_document(conn, 1)
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
    # FTS integrity must survive the delete
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('integrity-check')")


def test_delete_document_clears_vectors_via_index(tmp_path):
    # regression: delete must clean the ACTIVE vector backend (numpy fallback here),
    # not only the sqlite-vec table — otherwise np_vectors orphans grow forever
    from app.search.vectors import NumpyVectorIndex
    conn = _mk(tmp_path)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at) "
                 "VALUES (1,'a.txt','a','txt',3,'ready','h','2026-01-01')")
    conn.execute("INSERT INTO chunks(id,document_id,seq,text,embed_text) VALUES (1,1,0,'x','x')")
    conn.commit()
    vidx = NumpyVectorIndex(conn)
    vidx.add([(1, [0.1] * 384)])
    assert conn.execute("SELECT count(*) FROM np_vectors").fetchone()[0] == 1
    db.delete_document(conn, 1, vector_index=vidx)
    assert conn.execute("SELECT count(*) FROM np_vectors").fetchone()[0] == 0   # no orphan
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0


def test_assert_embed_dim_detects_model_change(tmp_path):
    import pytest
    conn = _mk(tmp_path)
    db.assert_embed_dim(conn, 384)          # first boot stamps the dimension
    db.assert_embed_dim(conn, 384)          # same model/dim → OK
    with pytest.raises(RuntimeError):
        db.assert_embed_dim(conn, 768)      # different-dim model → fail loudly, not corrupt KNN


def test_recover_interrupted_purges_partial_data(tmp_path):
    # a crash left the doc 'processing' with committed chunks — recovery must remove that
    # partial data (so it can't pollute search), not just relabel the status
    conn = _mk(tmp_path)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at) "
                 "VALUES (1,'a.txt','a','txt',3,'processing','h','2026-01-01')")
    conn.execute("INSERT INTO chunks(id,document_id,seq,text,embed_text) VALUES (1,1,0,'partial','partial')")
    conn.commit()
    db.recover_interrupted(conn)
    assert conn.execute("SELECT status FROM documents WHERE id=1").fetchone()[0] == "failed"
    assert conn.execute("SELECT count(*) FROM chunks WHERE document_id=1").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'partial'").fetchone()[0] == 0
