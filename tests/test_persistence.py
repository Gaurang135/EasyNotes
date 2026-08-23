from app import db
from app.persistence.backends import LocalSnapshotBackend
from app.persistence.snapshot import snapshot_db, restore_on_boot


def test_local_snapshot_and_restore(tmp_path):
    store = tmp_path / "store"; store.mkdir()
    dbp = tmp_path / "easynotes.db"
    conn = db.connect(str(dbp)); db.init_schema(conn)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at)"
                 " VALUES (1,'a','a','txt',1,'ready','h','2026')"); conn.commit()
    backend = LocalSnapshotBackend(str(store))
    snapshot_db(conn, backend, str(dbp))
    conn.close(); dbp.unlink()                      # simulate wiped ephemeral disk

    assert restore_on_boot(backend, str(dbp)) is True
    conn2 = db.connect(str(dbp)); db.init_schema(conn2)
    assert conn2.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


def test_restore_returns_false_when_no_snapshot(tmp_path):
    backend = LocalSnapshotBackend(str(tmp_path / "empty"))
    assert restore_on_boot(backend, str(tmp_path / "x.db")) is False


def test_app_survives_wiped_disk(tmp_path):
    """Full durability loop: ingest -> shutdown snapshot -> wipe -> restart -> data restored."""
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.settings import Settings
    from app.search.embeddings import FakeEmbedder

    overrides = {"DATA_DIR": str(tmp_path), "SNAPSHOT_BACKEND": "local"}
    with TestClient(create_app(Settings.from_env(overrides=overrides),
                               embedder=FakeEmbedder(dim=384))) as c:
        c.post("/documents/text", json={"title": "Keep", "text": "durable revenue note"})
        assert c.get("/search", params={"q": "revenue"}).json()["results"]
    # simulate the ephemeral free tier wiping the live DB (snapshot lives under _snapshots/)
    (tmp_path / "easynotes.db").unlink()
    for suffix in ("-wal", "-shm"):
        p = tmp_path / f"easynotes.db{suffix}"
        if p.exists():
            p.unlink()
    with TestClient(create_app(Settings.from_env(overrides=overrides),
                               embedder=FakeEmbedder(dim=384))) as c2:
        assert c2.get("/search", params={"q": "revenue"}).json()["results"], "corpus not restored"
