from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings


def test_healthz_ok(tmp_path):
    app = create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}))
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
