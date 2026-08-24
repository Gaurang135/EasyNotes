from __future__ import annotations
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.settings import Settings
from app import db
from app.ingest.parsers import PARSERS
from app.ingest.chunker import make_token_counter
from app.ingest.pipeline import IngestionPipeline
from app.ingest.queue import make_ingest_queue
from app.search.vectors import make_vector_index
from app.search.fts import Fts5Index
from app.search.embeddings import FastembedEmbedder
from app.persistence.backends import make_backend
from app.persistence.snapshot import restore_on_boot, snapshot_db
from app.api import documents, search, answer, structured


def create_app(settings: Settings | None = None, *, embedder=None, answer_synth=None) -> FastAPI:
    settings = settings or Settings.from_env()
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    backend = make_backend(settings)
    db_path = str(data_dir / "easynotes.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        restore_on_boot(backend, db_path)          # ephemeral-tier durability
        conn = db.ThreadLocalConn(db_path)          # per-thread connections (worker + requests)
        db.init_schema(conn)
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('data_dir',?)",
                     (str(data_dir),))
        conn.commit()
        app.state.settings = settings
        app.state.conn = conn
        app.state.parsers = PARSERS
        app.state.embedder = embedder or FastembedEmbedder(settings)
        app.state.vector_index = make_vector_index(conn)
        db.recover_interrupted(conn, app.state.vector_index)   # purge partial data from crashed ingests
        app.state.fts_index = Fts5Index(conn)
        app.state.backend = backend
        pipeline_backend = None if settings.snapshot_backend == "none" else backend
        app.state.pipeline = IngestionPipeline(
            conn, PARSERS, make_token_counter(settings),
            app.state.embedder, app.state.vector_index,
            backend=pipeline_backend, db_path=db_path)
        from app.answer import make_synthesizer
        app.state.answer_synth = answer_synth if answer_synth is not None else make_synthesizer(settings)
        app.state.ingest = make_ingest_queue(settings.ingest_mode, app.state.pipeline)
        app.state.ingest.start()
        # recover any documents left 'pending' by a crash/restart (never dropped)
        for (doc_id,) in conn.execute("SELECT id FROM documents WHERE status='pending'").fetchall():
            app.state.ingest.enqueue(doc_id)
        yield
        app.state.ingest.stop()
        try:
            snapshot_db(conn, backend, db_path)     # final snapshot on shutdown
        finally:
            conn.close_all()

    app = FastAPI(title="EasyNotes", lifespan=lifespan)
    app.include_router(documents.router)
    app.include_router(search.router)
    app.include_router(answer.router)
    app.include_router(structured.router)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    # Mount the static UI last so API routes take precedence.
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
    if os.path.isdir(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


app = create_app()
