from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_home():
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "Cérebro Comercial" in r.text
