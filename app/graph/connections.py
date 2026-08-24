"""Entity-connection graph: which documents are linked by the *same* extracted value
(a shared vendor, email, or date). Only entities shared by 2+ documents are shown —
single-document values are noise, not connections."""
from __future__ import annotations

DOC_COLOR = "#8892a6"
KIND_COLORS = {
    "amount": "#f2a65a", "date": "#5fd3c6", "email": "#8a7cff",
    "phone": "#e28fd0", "url": "#7fd08c", "pair": "#c9a26b",
}


def _entity_index(conn):
    """(kind, normalized value) -> {value, kind, docs:set[(id,title)]}"""
    entities: dict[tuple[str, str], dict] = {}
    for did, title, value, kind in conn.execute(
        "SELECT f.document_id, d.title, f.value, f.kind FROM fields f "
        "JOIN documents d ON d.id=f.document_id WHERE d.status='ready'"
    ):
        norm = (value or "").strip().lower()
        if not norm:
            continue
        e = entities.setdefault((kind, norm), {"value": value, "kind": kind, "docs": set()})
        e["docs"].add((did, title))
    return entities


def build_connection_graph(conn, q: str | None = None) -> dict:
    entities = _entity_index(conn)
    shared = {k: e for k, e in entities.items() if len(e["docs"]) >= 2}

    total_docs = conn.execute(
        "SELECT count(*) FROM documents WHERE status='ready'").fetchone()[0]

    ql = (q or "").strip().lower()
    nodes, edges = [], []
    connected_docs: dict[int, str] = {}
    connections = []               # readable summary list

    for (kind, norm), e in sorted(shared.items(), key=lambda kv: -len(kv[1]["docs"])):
        eid = f"e:{kind}:{norm}"
        deg = len(e["docs"])
        data = {"id": eid, "label": e["value"], "kind": "entity", "ekind": kind,
                "color": KIND_COLORS.get(kind, "#888"), "size": deg, "docs": deg}
        if ql and ql in norm:
            data["matched"] = True
        nodes.append({"data": data})
        doc_titles = []
        for did, title in sorted(e["docs"]):
            connected_docs[did] = title
            doc_titles.append(title)
            edges.append({"data": {"id": f"{eid}->{did}", "source": eid, "target": f"d{did}"}})
        connections.append({"value": e["value"], "kind": kind, "count": deg, "documents": doc_titles})

    for did, title in connected_docs.items():
        nodes.append({"data": {"id": f"d{did}", "label": title, "kind": "doc",
                               "color": DOC_COLOR, "size": 10}})

    return {"nodes": nodes, "edges": edges, "connections": connections,
            "counts": {"documents": total_docs, "connected": len(connected_docs),
                       "shared_entities": len(shared),
                       "isolated": total_docs - len(connected_docs)}}
