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


def test_mark_interrupted(tmp_path):
    conn = _mk(tmp_path)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at) "
                 "VALUES (1,'a.txt','a','txt',3,'processing','h','2026-01-01')")
    conn.commit()
    db.mark_interrupted(conn)
    assert conn.execute("SELECT status FROM documents WHERE id=1").fetchone()[0] == "failed"
