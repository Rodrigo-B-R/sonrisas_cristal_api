"""Test setup. The tests run on SQLite (a temporary file): no PostgreSQL needed.

The database triggers (audit) are not tested here: they live in sonrisas_cristal_db.
"""

import os
import tempfile

# Must be set BEFORE the app is imported: settings are read once.
_tmp = tempfile.mkdtemp(prefix="sonrisas_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["JWT_SECRET"] = "test-secret-for-the-tests-only-0123456789abcdef"
os.environ["TZ"] = "America/Monterrey"
os.environ["ENVIRONMENT"] = "development"
os.environ["METRICS_TOKEN"] = "metrics-test-token"
os.environ["LOGIN_RATE_LIMIT"] = "5/minute"
os.environ["LOGIN_MAX_FAILURES"] = "10"
os.environ["TRUSTED_PROXIES"] = "10.0.0.0/8"
os.environ["LATE_TOLERANCE_MINUTES"] = "5"

import logging  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.security as security  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.logging_config import security_log  # noqa: E402
from app.main import app  # noqa: E402
from app.security import limiter, login_guard, token_denylist  # noqa: E402
from tests import factories  # noqa: E402

PASSWORD = "Secret123"


@pytest.fixture(autouse=True)
def fresh_database():
    """Empty tables, empty brute-force counters and no rate limit (a test turns it on if it needs it)."""
    security.BCRYPT_ROUNDS = 4  # real hashing (cost 12) would make every test slow
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_guard._attempts.clear()
    token_denylist._revoked.clear()
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.enabled = False


@pytest.fixture
def world(fresh_database):
    """Two daycares with a director, and in each a manager and an employee. Returns their ids."""
    with SessionLocal() as db:
        return factories.build_world(db, PASSWORD)


@pytest.fixture
def client(world):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def login(client):
    """login("manager_a") -> {"Authorization": "Bearer ..."}"""

    def _login(username: str) -> dict:
        response = client.post("/login", json={"username": username, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    return _login


@pytest.fixture
def security_events():
    """The security events logged during the test (the logger does not propagate, so caplog cannot see it)."""
    records: list[dict] = []

    class Collector(logging.Handler):
        def emit(self, record):
            records.append(getattr(record, "fields", {}))

    handler = Collector()
    security_log.addHandler(handler)
    yield records
    security_log.removeHandler(handler)
