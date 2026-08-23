"""Single-writer ingest queue. Guarantees every enqueued document is processed
exactly once, in order, with no threadpool starvation under upload bursts.

- threaded (production/local): one daemon worker drains a queue sequentially, so
  uploads return immediately (status 'pending') and the UI polls to 'ready'.
- inline (tests): runs synchronously on enqueue, so TestClient sees 'ready' at once.
"""
from __future__ import annotations
import queue as _queue
import threading
import logging

log = logging.getLogger("easynotes.queue")


class InlineIngestQueue:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    def enqueue(self, document_id: int) -> None:
        self.pipeline.ingest(document_id)

    def start(self) -> None: ...
    def stop(self) -> None: ...


class ThreadedIngestQueue:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self._q: _queue.Queue[int] = _queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ingest-worker", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                doc_id = self._q.get(timeout=0.5)
            except _queue.Empty:
                continue
            try:
                self.pipeline.ingest(doc_id)
            except Exception:                     # never let the worker die
                log.exception("ingest failed for %s", doc_id)
            finally:
                self._q.task_done()

    def enqueue(self, document_id: int) -> None:
        self._q.put(document_id)

    def stop(self) -> None:
        self._stop.set()


def make_ingest_queue(mode: str, pipeline):
    return InlineIngestQueue(pipeline) if mode == "inline" else ThreadedIngestQueue(pipeline)
