from fastapi.testclient import TestClient

from rondo import __version__
from rondo.api.app import app


def test_health():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
