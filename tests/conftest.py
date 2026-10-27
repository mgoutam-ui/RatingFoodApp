import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key",
        "DATABASE_BACKEND": "sqlite",
        "DATABASE": str(tmp_path / "test.sqlite3"),
    })
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, username="bronco", password="secure-pass-123"):
    return client.post(
        "/register",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def login(client, username="bronco", password="secure-pass-123"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
