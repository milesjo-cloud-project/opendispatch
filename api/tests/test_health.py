from fastapi.testclient import TestClient

from app.main import app, get_db_health

client = TestClient(app)


class UpDb:
    def ping(self) -> bool:
        return True


class DownDb:
    def ping(self) -> bool:
        return False


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_up():
    app.dependency_overrides[get_db_health] = UpDb
    try:
        assert client.get("/readyz").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_readyz_down():
    app.dependency_overrides[get_db_health] = DownDb
    try:
        assert client.get("/readyz").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_docs_available_locally():
    # Tests run with APP_ENV=local; in dev/prod docs_url is None (see main.py).
    assert client.get("/docs").status_code == 200
