from __future__ import annotations
import tempfile
import os
from pathlib import Path
from app.persistence.backends import SNAPSHOT_KEY


def snapshot_db(conn, backend, db_path: str) -> None:
    """Consistent snapshot via VACUUM INTO (safe under concurrent writes), then upload."""
    with tempfile.TemporaryDirectory() as d:
        tmp = os.path.join(d, "snap.db")
        conn.execute("VACUUM INTO ?", (tmp,))
        backend.put(SNAPSHOT_KEY, tmp)


def restore_on_boot(backend, db_path: str) -> bool:
    """If the local DB is missing and a snapshot exists, install it. Returns True if restored."""
    if Path(db_path).exists():
        return False
    if not backend.exists(SNAPSHOT_KEY):
        return False
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return backend.get(SNAPSHOT_KEY, db_path)
