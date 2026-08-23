"""Entity-connection graph: documents linked to the structured values extracted from
them (vendors, emails, dates, amounts…). Documents that share an entity cluster
together — turning the extraction layer into a navigable map of the corpus."""
from __future__ import annotations

DOC_COLOR = "#8892a6"
KIND_COLORS = {
    "amount": "#f2a65a", "date": "#5fd3c6", "email": "#8a7cff",
    "phone": "#e28fd0", "url": "#7fd08c", "pair": "#c9a26b",
}


def build_connection_graph(conn, q: str | None = None) -> dict:
    docs = conn.execute(
        "SELECT id, title, file_type FROM documents WHERE status='ready'").fetchall()
    doc_ids = {d[0] for d in docs}
    nodes = [{"data": {"id": f"d{did}", "label": title, "kind": "doc",
                       "file_type": ftype, "color": DOC_COLOR, "size": 8}}
             for did, title, ftype in docs]

    entities: dict[tuple[str, str], dict] = {}
    for did, value, kind in conn.execute("SELECT document_id, value, kind FROM fields"):
        if did not in doc_ids:
            continue
        norm = value.strip().lower()
        if not norm:
            continue
        e = entities.setdefault((kind, norm), {"value": value, "kind": kind, "docs": set()})
        e["docs"].add(did)

    ql = (q or "").strip().lower()
    edges = []
    for (kind, norm), e in entities.items():
        eid = f"e:{kind}:{norm}"
        deg = len(e["docs"])
        data = {"id": eid, "label": e["value"], "kind": "entity", "ekind": kind,
                "color": KIND_COLORS.get(kind, "#888"), "size": deg, "shared": deg > 1,
                "docs": deg}
        if ql and ql in norm:
            data["matched"] = True
        nodes.append({"data": data})
        for did in e["docs"]:
            edges.append({"data": {"id": f"{eid}->{did}", "source": eid, "target": f"d{did}"}})

    return {"nodes": nodes, "edges": edges,
            "counts": {"documents": len(docs), "entities": len(entities),
                       "shared": sum(1 for e in entities.values() if len(e["docs"]) > 1)}}
