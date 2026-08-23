import os

# Tests run ingestion synchronously (inline) so TestClient sees 'ready' immediately,
# without a background worker thread. Production/local default to the threaded worker.
os.environ.setdefault("INGEST_MODE", "inline")
