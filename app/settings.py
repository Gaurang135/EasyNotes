from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    data_dir: str = "./data"
    max_upload_mb: int = 25
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_model_path: str | None = None      # baked snapshot dir; used for the tokenizer
    embed_cache_dir: str | None = None       # HF cache root; enables offline load with HF_HUB_OFFLINE
    embed_threads: int = 1
    embed_batch_size: int = 16
    snapshot_backend: str = "none"           # none | local | s3
    snapshot_endpoint: str | None = None
    snapshot_bucket: str | None = None
    snapshot_access_key: str | None = None
    snapshot_secret_key: str | None = None
    snapshot_interval_s: int = 300
    ingest_mode: str = "threaded"            # threaded (worker) | inline (synchronous, tests)
    answer_base_url: str | None = None       # OpenAI-compatible endpoint for the optional RAG layer
    answer_api_key: str | None = None
    answer_model: str | None = None          # set model + (key or base_url) to enable /answer

    @staticmethod
    def from_env(overrides: dict | None = None) -> "Settings":
        env = dict(os.environ)
        if overrides:
            env.update(overrides)
        g = env.get
        return Settings(
            data_dir=g("DATA_DIR", "./data"),
            max_upload_mb=int(g("MAX_UPLOAD_MB", "25")),
            embed_model=g("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
            embed_model_path=g("EMBED_MODEL_PATH") or None,
            embed_cache_dir=g("EMBED_CACHE_DIR") or None,
            embed_threads=int(g("EMBED_THREADS", "1")),
            embed_batch_size=int(g("EMBED_BATCH_SIZE", "16")),
            snapshot_backend=g("SNAPSHOT_BACKEND", "none"),
            snapshot_endpoint=g("SNAPSHOT_ENDPOINT") or None,
            snapshot_bucket=g("SNAPSHOT_BUCKET") or None,
            snapshot_access_key=g("SNAPSHOT_ACCESS_KEY") or None,
            snapshot_secret_key=g("SNAPSHOT_SECRET_KEY") or None,
            snapshot_interval_s=int(g("SNAPSHOT_INTERVAL_S", "300")),
            ingest_mode=g("INGEST_MODE", "threaded"),
            answer_base_url=g("ANSWER_BASE_URL") or None,
            answer_api_key=g("ANSWER_API_KEY") or None,
            answer_model=g("ANSWER_MODEL") or None,
        )
