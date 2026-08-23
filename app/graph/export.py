from __future__ import annotations
import xml.sax.saxutils as sx

_COLORS = {"pdf": "#e2504a", "docx": "#2b579a", "pptx": "#d24726", "xlsx": "#217346",
           "csv": "#4c9a2a", "md": "#555", "txt": "#888"}


def _doc_nodes(conn, matched):
    rows = conn.execute(
        "SELECT d.id, d.title, d.file_type, count(c.id) "
        "FROM documents d LEFT JOIN chunks c ON c.document_id=d.id "
        "WHERE d.status='ready' GROUP BY d.id").fetchall()
    nodes = []
    matched = matched or {}
    matched_docs = {}
    if matched:
        for cid, score in matched.items():
            r = conn.execute("SELECT document_id FROM chunks WHERE id=?", (cid,)).fetchone()
            if r:
                matched_docs[r[0]] = max(matched_docs.get(r[0], 0.0), score)
    for did, title, ftype, n in rows:
        data = {"id": f"d{did}", "label": title, "file_type": ftype,
                "size": max(n, 1), "color": _COLORS.get(ftype, "#888")}
        if did in matched_docs:
            data["matched"] = True
            data["match_score"] = matched_docs[did]
        nodes.append({"data": data})
    return nodes


def _edges(conn):
    rows = conn.execute(
        "SELECT e.src_chunk_id, e.dst_chunk_id, e.score, cs.document_id, cd.document_id "
        "FROM similarity_edges e "
        "JOIN chunks cs ON cs.id=e.src_chunk_id JOIN chunks cd ON cd.id=e.dst_chunk_id").fetchall()
    scores = [r[2] for r in rows] or [0, 1]
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0
    edges = []
    for src, dst, score, sdoc, ddoc in rows:
        if sdoc == ddoc:
            continue
        width = 1 + 5 * (score - lo) / span      # rescale within observed range
        edges.append({"data": {"id": f"e{src}_{dst}", "source": f"d{sdoc}", "target": f"d{ddoc}",
                               "source_doc": sdoc, "target_doc": ddoc,
                               "weight": round(width, 2), "score": round(score, 3)}})
    return edges


def to_cytoscape(conn, matched=None) -> dict:
    return {"nodes": _doc_nodes(conn, matched), "edges": _edges(conn)}


def to_graphml(conn) -> str:
    g = to_cytoscape(conn)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns"><graph edgedefault="undirected">']
    for n in g["nodes"]:
        out.append(f'<node id="{n["data"]["id"]}"><data key="label">'
                   f'{sx.escape(n["data"]["label"])}</data></node>')
    for e in g["edges"]:
        out.append(f'<edge source="{e["data"]["source"]}" target="{e["data"]["target"]}"/>')
    out.append("</graph></graphml>")
    return "\n".join(out)
