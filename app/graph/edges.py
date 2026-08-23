from __future__ import annotations

EDGE_TOP_K = 5
EDGE_FLOOR = 0.35   # calibrated floor so unrelated docs don't all connect


def compute_edges_for_document(conn, vector_index, document_id: int,
                               top_k: int = EDGE_TOP_K, floor: float = EDGE_FLOOR) -> None:
    chunk_ids = [r[0] for r in conn.execute(
        "SELECT id FROM chunks WHERE document_id=?", (document_id,))]
    for cid in chunk_ids:
        vec = _vector_for(conn, vector_index, cid)
        if vec is None:
            continue
        for sc in vector_index.search(vec, top_k + 10):
            if sc.chunk_id == cid or sc.score < floor:
                continue
            other_doc = conn.execute("SELECT document_id FROM chunks WHERE id=?",
                                     (sc.chunk_id,)).fetchone()
            if not other_doc or other_doc[0] == document_id:
                continue                       # cross-document edges only
            a, b = sorted((cid, sc.chunk_id))
            conn.execute("INSERT OR REPLACE INTO similarity_edges(src_chunk_id,dst_chunk_id,score) "
                         "VALUES (?,?,?)", (a, b, sc.score))
    conn.commit()


def _vector_for(conn, vector_index, chunk_id):
    if _has_table(conn, "np_vectors"):
        row = conn.execute("SELECT vec FROM np_vectors WHERE chunk_id=?", (chunk_id,)).fetchone()
        if row:
            import numpy as np
            return np.frombuffer(row[0], dtype=np.float32).tolist()
    if _has_table(conn, "chunk_vectors"):
        r = conn.execute("SELECT embedding FROM chunk_vectors WHERE chunk_id=?", (chunk_id,)).fetchone()
        if r:
            import struct
            return list(struct.unpack("%sf" % (len(r[0]) // 4), r[0]))
    return None


def _has_table(conn, name) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
