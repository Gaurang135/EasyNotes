"""Contract tests proving the swappable seams honor one substitutable behavior."""
import math
import time
import threading
import pytest
from app.ingest.queue import InlineIngestQueue, ThreadedIngestQueue
from app.search.embeddings import FakeEmbedder
from app.answer import FakeSynthesizer
from app.models import SearchHit


# ---------- ingest queue: Inline and Threaded are substitutable ----------
class _RecordingPipeline:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def ingest(self, doc_id):
        with self._lock:
            self.calls.append(doc_id)


def _drain(pipeline, n, timeout=2.0):
    deadline = time.time() + timeout
    while len(pipeline.calls) < n and time.time() < deadline:
        time.sleep(0.01)


@pytest.mark.parametrize("Queue", [InlineIngestQueue, ThreadedIngestQueue])
def test_queue_processes_each_document_once_in_order(Queue):
    p = _RecordingPipeline()
    q = Queue(p)
    q.start()
    for i in (1, 2, 3):
        q.enqueue(i)
    _drain(p, 3)
    q.stop()
    assert p.calls == [1, 2, 3]        # exactly once, in order (single writer)


def test_threaded_worker_survives_a_failing_item():
    class Flaky:
        def __init__(self):
            self.calls = []

        def ingest(self, doc_id):
            self.calls.append(doc_id)
            if doc_id == 1:
                raise ValueError("boom")

    p = Flaky()
    q = ThreadedIngestQueue(p)
    q.start()
    q.enqueue(1)
    q.enqueue(2)
    _drain(p, 2)
    q.stop()
    assert p.calls == [1, 2]           # item 1 failing must not kill the worker


# ---------- embedder contract ----------
def test_fake_embedder_contract():
    e = FakeEmbedder(dim=16)
    vs = e.embed_passages(["hello", "world"])
    assert len(vs) == 2 and all(len(v) == 16 for v in vs)          # dim honored
    assert e.embed_passages(["hello"])[0] == e.embed_passages(["hello"])[0]  # deterministic
    assert e.embed_query("hello") != e.embed_passages(["hello"])[0]  # asymmetric query/passage
    assert abs(math.sqrt(sum(x * x for x in e.embed_query("hi"))) - 1.0) < 1e-6  # normalized


# ---------- synthesizer contract ----------
def test_fake_synthesizer_contract():
    hit = SearchHit(chunk_id=1, document_id=2, document_title="Doc", file_type="txt",
                    snippet="s", text="t", location="l", score=1.0)
    r = FakeSynthesizer().answer("what?", [hit])
    assert set(r) == {"answer", "citations"}
    assert isinstance(r["answer"], str) and r["answer"]
    assert r["citations"][0]["document_id"] == 2                    # citation points at the source doc
