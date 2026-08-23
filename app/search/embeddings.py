from __future__ import annotations
import hashlib
import math
from typing import Protocol, Sequence, runtime_checkable

BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@runtime_checkable
class Embedder(Protocol):
    dim: int
    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FakeEmbedder:
    """Deterministic hash-based embeddings for tests. No model load."""
    def __init__(self, dim: int = 8):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        raw = [h[i % len(h)] / 255.0 for i in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(BGE_QUERY_INSTRUCTION + text)


class FastembedEmbedder:
    dim = 384

    def __init__(self, settings):
        from fastembed import TextEmbedding
        kwargs = {"threads": settings.embed_threads}
        if settings.embed_model_path:
            kwargs["specific_model_path"] = settings.embed_model_path
        else:
            kwargs["model_name"] = settings.embed_model
        # never pass parallel= : it forks whole model copies (OOM on 512MB)
        self._model = TextEmbedding(**kwargs)
        self._batch = settings.embed_batch_size

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts), batch_size=self._batch)]

    def embed_query(self, text: str) -> list[float]:
        return list(self._model.embed([BGE_QUERY_INSTRUCTION + text]))[0].tolist()
