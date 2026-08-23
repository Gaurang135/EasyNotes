from __future__ import annotations
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.settings import Settings
from app import db
from app.ingest.parsers import PARSERS
from app.ingest.chunker import make_token_counter
from app.ingest.pipeline import IngestionPipeline
from app.search.vectors import make_vector_index
from app.search.fts import Fts5Index
from app.search.embeddings import FastembedEmbedder
from app.api import documents, search, graph


def create_app(settings: Settings | None = None, *, embedder=None) -> FastAPI:
    settings = settings or Settings.from_env()
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.connect(str(data_dir / "easynotes.db"))
        db.init_schema(conn)
        db.mark_interrupted(conn)
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('data_dir',?)",
                     (str(data_dir),))
        conn.commit()
        app.state.settings = settings
        app.state.conn = conn
        app.state.parsers = PARSERS
        app.state.embedder = embedder or FastembedEmbedder(settings)
        app.state.vector_index = make_vector_index(conn)
        app.state.fts_index = Fts5Index(conn)
        app.state.pipeline = IngestionPipeline(
            conn, PARSERS, make_token_counter(settings),
            app.state.embedder, app.state.vector_index,
            edge_floor=settings.edge_floor)
        yield
        conn.close()

    app = FastAPI(title="EasyNotes", lifespan=lifespan)
    app.include_router(documents.router)
    app.include_router(search.router)
    app.include_router(graph.router)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
