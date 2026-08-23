from __future__ import annotations
from typing import Protocol, Sequence
import numpy as np
from app.models import ScoredChunk


class VectorIndex(Protocol):
    def add(self, items: Sequence[tuple[int, list[float]]]) -> None: ...
    def search(self, vector: list[float], k: int) -> list[ScoredChunk]: ...
    def delete_document(self, document_id: int) -> None: ...


class NumpyVectorIndex:
    """Brute-force cosine over vectors stored in a plain table. Fallback + test default."""
    def __init__(self, conn):
        self.conn = conn
        conn.execute("CREATE TABLE IF NOT EXISTS np_vectors "
                     "(chunk_id INTEGER PRIMARY KEY, vec BLOB NOT NULL)")
        conn.commit()

    def add(self, items):
        for cid, vec in items:
            arr = np.asarray(vec, dtype=np.float32)  # float32 — never let float64 double memory
            self.conn.execute("INSERT OR REPLACE INTO np_vectors(chunk_id, vec) VALUES (?,?)",
                              (cid, arr.tobytes()))
        self.conn.commit()

    def search(self, vector, k):
        rows = self.conn.execute("SELECT chunk_id, vec FROM np_vectors").fetchall()
        if not rows:
            return []
        q = np.asarray(vector, dtype=np.float32)
        qn = q / (np.linalg.norm(q) or 1.0)
        ids = [r[0] for r in rows]
        mat = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), -1)
        norms = np.linalg.norm(mat, axis=1)
        norms[norms == 0] = 1.0
        sims = (mat @ qn) / norms
        top = np.argsort(-sims)[:k]
        return [ScoredChunk(chunk_id=ids[i], score=float(sims[i])) for i in top]

    def delete_document(self, document_id):
        self.conn.execute(
            "DELETE FROM np_vectors WHERE chunk_id IN "
            "(SELECT id FROM chunks WHERE document_id=?)", (document_id,))
        self.conn.commit()


class SqliteVecIndex:
    """vec0-backed. Cosine distance -> similarity conversion lives ONLY here."""
    def __init__(self, conn):
        self.conn = conn

    def add(self, items):
        import struct
        for cid, vec in items:
            blob = struct.pack("%sf" % len(vec), *vec)
            self.conn.execute("INSERT OR REPLACE INTO chunk_vectors(chunk_id, embedding) VALUES (?,?)",
                              (cid, blob))
        self.conn.commit()

    def search(self, vector, k):
        import struct
        blob = struct.pack("%sf" % len(vector), *vector)
        # k=? form (never LIMIT); no join onto MATCH
        rows = self.conn.execute(
            "SELECT chunk_id, distance FROM chunk_vectors "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (blob, k)).fetchall()
        return [ScoredChunk(chunk_id=cid, score=1.0 - dist) for cid, dist in rows]

    def delete_document(self, document_id):
        ids = [r[0] for r in self.conn.execute(
            "SELECT id FROM chunks WHERE document_id=?", (document_id,))]
        for cid in ids:
            self.conn.execute("DELETE FROM chunk_vectors WHERE chunk_id=?", (cid,))
        self.conn.commit()


def make_vector_index(conn) -> VectorIndex:
    if getattr(conn, "vec_available", False):
        return SqliteVecIndex(conn)
    return NumpyVectorIndex(conn)
