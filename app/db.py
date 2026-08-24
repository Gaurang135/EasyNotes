from __future__ import annotations
import logging
import sqlite3
import threading

log = logging.getLogger("easynotes.db")
EMBED_DIM = 384

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL,
  title TEXT NOT NULL,
  file_type TEXT NOT NULL,
  size INTEGER NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  warnings TEXT,
  content_hash TEXT UNIQUE,
  uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  seq INTEGER NOT NULL,
  text TEXT NOT NULL,
  embed_text TEXT NOT NULL,
  location TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text,
  content='chunks',
  content_rowid='id',
  tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- Structured extraction (Mode A: precise/defined queries) --------------------
CREATE TABLE IF NOT EXISTS tables (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  name TEXT NOT NULL,
  columns TEXT NOT NULL,          -- JSON array of name/type column defs
  location TEXT,
  row_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tables_doc ON tables(document_id);
CREATE TABLE IF NOT EXISTS table_rows (
  table_id INTEGER NOT NULL REFERENCES tables(id),
  row_index INTEGER NOT NULL,
  data TEXT NOT NULL              -- JSON array of cell strings
);
CREATE INDEX IF NOT EXISTS idx_rows_table ON table_rows(table_id);
CREATE TABLE IF NOT EXISTS fields (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  kind TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fields_doc ON fields(document_id);
CREATE INDEX IF NOT EXISTS idx_fields_kind ON fields(kind);
"""


def _load_vec(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec into this connection. Returns False on any failure."""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except (AttributeError, sqlite3.OperationalError, Exception) as e:  # noqa: BLE001
        log.warning("sqlite-vec unavailable, using numpy fallback: %s", e)
        return False


class _Conn(sqlite3.Connection):
    """sqlite3.Connection subclass so we can attach vec_available (C type has no __dict__)."""
    vec_available: bool = False


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, factory=_Conn)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.vec_available = _load_vec(conn)
    return conn


class ThreadLocalConn:
    """Proxy that hands each thread its own real connection to the same DB file.

    One shared sqlite3 connection used concurrently from the ingest worker + request
    threads raises 'bad parameter or other API misuse'. WAL allows many connections,
    so each thread lazily gets its own; all `.execute/.commit/…` calls forward to it,
    leaving every existing call site (`conn.execute(...)`) unchanged.
    """
    def __init__(self, path: str):
        self._path = path
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []

    def _c(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = connect(self._path)
            self._local.c = c
            self._all.append(c)
        return c

    @property
    def vec_available(self) -> bool:
        return bool(getattr(self._c(), "vec_available", False))

    def __getattr__(self, name):
        return getattr(self._c(), name)

    def close_all(self) -> None:
        for c in self._all:
            try:
                c.close()
            except Exception:
                pass


def sqlite_vec_available(path: str) -> bool:
    ver = sqlite3.sqlite_version_info
    log.info("sqlite runtime version %s", sqlite3.sqlite_version)
    if ver < (3, 41, 0):
        log.warning("SQLite %s < 3.41; sqlite-vec KNN unsupported, using numpy", sqlite3.sqlite_version)
        return False
    c = sqlite3.connect(path)
    ok = _load_vec(c)
    c.close()
    return ok


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if getattr(conn, "vec_available", False):
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0("
            f"chunk_id INTEGER PRIMARY KEY, embedding float[{EMBED_DIM}] distance_metric=cosine)"
        )
    conn.commit()


def _delete_children(conn: sqlite3.Connection, document_id: int) -> None:
    """Delete everything derived from a document EXCEPT the documents row itself:
    chunks (FTS cleaned by triggers), table_rows, tables, fields."""
    conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
    tids = [r[0] for r in conn.execute(
        "SELECT id FROM tables WHERE document_id=?", (document_id,))]
    for tid in tids:
        conn.execute("DELETE FROM table_rows WHERE table_id=?", (tid,))
    conn.execute("DELETE FROM tables WHERE document_id=?", (document_id,))
    conn.execute("DELETE FROM fields WHERE document_id=?", (document_id,))


def delete_document(conn: sqlite3.Connection, document_id: int, vector_index=None) -> None:
    # Vector rows are cleaned through the active VectorIndex (numpy OR sqlite-vec), so the
    # cleanup lives in exactly one backend-agnostic place — never a table-specific DELETE
    # here that silently misses the other backend.
    if vector_index is not None:
        vector_index.delete_document(document_id)
    try:
        conn.execute("BEGIN")
        _delete_children(conn, document_id)
        conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def set_status(conn, document_id, status, error=None, warnings=None) -> None:
    import json
    conn.execute(
        "UPDATE documents SET status=?, error=?, warnings=? WHERE id=?",
        (status.value if hasattr(status, "value") else status, error,
         json.dumps(warnings or []), document_id),
    )
    conn.commit()


def recover_interrupted(conn, vector_index=None) -> None:
    """A crash can leave a document 'processing' with partially-written chunks/vectors/
    tables/fields (they're committed in stages). On boot, purge that partial data so it
    can't pollute keyword/semantic search, and mark the document failed('interrupted')."""
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM documents WHERE status='processing'")]
    for did in ids:
        if vector_index is not None:
            vector_index.delete_document(did)
        try:
            conn.execute("BEGIN")
            _delete_children(conn, did)
            conn.execute("UPDATE documents SET status='failed', error='interrupted' WHERE id=?", (did,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
