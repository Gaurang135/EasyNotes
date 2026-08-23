from __future__ import annotations
import logging
from pathlib import Path
from app import db
from app.models import Status
from app.errors import ParseError
from app.ingest.validation import check_archive_safety

log = logging.getLogger("easynotes.pipeline")


class IngestionPipeline:
    def __init__(self, conn, parsers, count_tokens, embedder, vector_index,
                 backend=None, db_path=None, edge_floor=0.35):
        self.conn = conn
        self.parsers = parsers
        self.count_tokens = count_tokens
        self.embedder = embedder
        self.vector_index = vector_index
        self.backend = backend
        self.db_path = db_path
        self.edge_floor = edge_floor

    def ingest(self, document_id: int) -> None:
        from app.ingest.chunker import chunk_document
        row = self.conn.execute(
            "SELECT filename, title, file_type FROM documents WHERE id=?",
            (document_id,)).fetchone()
        if not row:
            return
        filename, title, file_type = row
        db.set_status(self.conn, document_id, Status.PROCESSING)
        try:
            parser = self.parsers.get(file_type)
            if parser is None:
                raise ParseError(f"unsupported file type: {file_type}")
            path = Path(self._data_dir()) / "originals" / f"{document_id}_{filename}"
            check_archive_safety(path, file_type)
            parsed = parser.parse(path)
            chunks = chunk_document(parsed, document_id, title, self.count_tokens)
            if not chunks:
                raise ParseError("no extractable text")
            vectors = self.embedder.embed_passages([c.embed_text for c in chunks])
            items = []
            for c, vec in zip(chunks, vectors):
                cur = self.conn.execute(
                    "INSERT INTO chunks(document_id,seq,text,embed_text,location) VALUES (?,?,?,?,?)",
                    (c.document_id, c.seq, c.text, c.embed_text, c.location))
                items.append((cur.lastrowid, vec))
            self.conn.commit()                       # triggers populate FTS
            self.vector_index.add(items)
            db.set_status(self.conn, document_id, Status.READY, warnings=parsed.warnings)
            self._post_ready(document_id)
        except ParseError as e:
            db.set_status(self.conn, document_id, Status.FAILED, error=e.reason)
        except Exception as e:                        # never crash the service
            log.exception("ingest failed for %s", document_id)
            db.set_status(self.conn, document_id, Status.FAILED, error=f"internal error: {e}")

    def _post_ready(self, document_id: int) -> None:
        from app.graph.edges import compute_edges_for_document
        compute_edges_for_document(self.conn, self.vector_index, document_id, floor=self.edge_floor)
        # snapshot on the write event so the data-loss window on an uploaded doc is ~zero
        if self.backend is not None and self.db_path:
            from app.persistence.snapshot import snapshot_db
            snapshot_db(self.conn, self.backend, self.db_path)

    def _data_dir(self) -> str:
        return self.conn.execute("SELECT value FROM meta WHERE key='data_dir'").fetchone()[0]
