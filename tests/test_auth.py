"""Login, tokens, rate limit and account lockout (OWASP A07), and stale tokens (A01)."""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Role, User
from app.security import limiter, login_guard
from tests.conftest import PASSWORD


def token_for(user_id, algorithm="HS256", expires_in=3600, secret=None, **extra):
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(seconds=expires_in), **extra}
    return jwt.encode(payload, secret or settings.jwt_secret, algorithm=algorithm)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ── Login ────────────────────────────────────────────────────────────


def test_login_returns_token_and_english_role(client):
    response = client.post("/login", json={"username": "manager_a", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "manager"
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == 3600
    assert body["user"]["name"] == "Manager A"


def test_wrong_password_and_unknown_user_look_the_same(client):
    wrong = client.post("/login", json={"username": "manager_a", "password": "nope"})
    unknown = client.post("/login", json={"username": "nobody", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"error": "Invalid username or password"}


def test_inactive_user_cannot_log_in(client, world):
    with SessionLocal() as db:
        db.get(User, world["ids"]["employee_a"]).is_active = False
        db.commit()
    response = client.post("/login", json={"username": "employee_a", "password": PASSWORD})
    assert response.status_code == 401


def test_login_validates_the_body(client):
    response = client.post("/login", json={"username": "x"})
    assert response.status_code == 400
    assert response.json()["error"] == "Invalid data"


# ── Tokens ───────────────────────────────────────────────────────────


def test_missing_and_invalid_tokens(client):
    assert client.get("/profile").json() == {"error": "Missing token"}
    assert client.get("/profile", headers=bearer("garbage")).json() == {"error": "Invalid token"}


def test_expired_token(client, world):
    response = client.get("/profile", headers=bearer(token_for(world["ids"]["manager_a"], expires_in=-10)))
    assert response.status_code == 401
    assert response.json() == {"error": "Token expired"}


def test_token_signed_with_another_secret_or_algorithm_is_rejected(client, world):
    user_id = world["ids"]["manager_a"]
    assert client.get("/profile", headers=bearer(token_for(user_id, secret="x" * 40))).status_code == 401
    # same secret but another algorithm: the API only accepts HS256
    assert client.get("/profile", headers=bearer(token_for(user_id, algorithm="HS512"))).status_code == 401
    # "none" algorithm
    unsigned = jwt.encode({"sub": str(user_id), "exp": 9999999999}, key=None, algorithm="none")
    assert client.get("/profile", headers=bearer(unsigned)).status_code == 401


def test_token_without_subject_is_rejected(client):
    token = jwt.encode({"exp": 9999999999}, settings.jwt_secret, algorithm="HS256")
    assert client.get("/profile", headers=bearer(token)).status_code == 401


def test_role_in_the_token_is_ignored(client, world):
    """Someone who forges a role claim gains nothing: the role comes from the database."""
    token = token_for(world["ids"]["employee_a"], role="director", daycare_id=999)
    response = client.get("/staff", headers=bearer(token))
    assert response.status_code == 403


# ── A01: the token never goes stale ──────────────────────────────────


def test_role_change_applies_immediately(client, login, world):
    headers = login("manager_a")
    assert client.get("/staff", headers=headers).status_code == 200
    with SessionLocal() as db:
        employee_role = db.query(Role).filter(Role.name == "empleada").one()
        db.get(User, world["ids"]["manager_a"]).role_id = employee_role.id
        db.commit()
    assert client.get("/staff", headers=headers).status_code == 403  # same token, new role


def test_termination_applies_immediately(client, login, world):
    employee = login("employee_a")
    assert client.get("/profile", headers=employee).status_code == 200
    manager = login("manager_a")
    response = client.post(
        f"/staff/{world['ids']['employee_a']}/terminate", headers=manager, json={"terminationReasonId": 1}
    )
    assert response.status_code == 200
    assert client.get("/profile", headers=employee).status_code == 401  # the token is still valid, the person is not


def test_transfer_applies_immediately(client, login, world):
    manager_a = login("manager_a")
    employee = login("employee_a")
    director = login("director")
    assert client.get("/rooms", headers=employee).json()[0]["daycareId"] == world["daycare_a"]
    response = client.post(
        f"/staff/{world['ids']['employee_a']}/transfer", headers=director, json={"daycareId": world["daycare_b"]}
    )
    assert response.status_code == 200
    # Same token, now in daycare B
    assert client.get("/rooms", headers=employee).json()[0]["daycareId"] == world["daycare_b"]
    assert client.get(f"/staff/{world['ids']['employee_a']}", headers=manager_a).status_code == 404


# ── A07: rate limit and lockout ──────────────────────────────────────


def test_login_is_rate_limited_per_ip(client):
    limiter.enabled = True
    limiter.reset()
    statuses = [
        client.post("/login", json={"username": f"user{i}", "password": "nope"}).status_code for i in range(7)
    ]
    assert statuses[:5] == [401] * 5
    assert statuses[5:] == [429, 429]
    blocked = client.post("/login", json={"username": "manager_a", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["error"].startswith("Too many requests")
    assert blocked.headers["Retry-After"]


def test_rate_limit_counts_the_real_client_ip_behind_the_proxy(world):
    """Behind the tunnel every request comes from the proxy: the real IP is in a header, but only a
    trusted proxy may say so."""
    limiter.enabled = True
    limiter.reset()

    counter = iter(range(1000))

    def attempt(test_client, ip):
        # a different username each time, so the account lockout does not get in the way
        body = {"username": f"user{next(counter)}", "password": "y"}
        return test_client.post("/login", json=body, headers={"CF-Connecting-IP": ip}).status_code

    with TestClient(app, client=("10.1.2.3", 5000)) as trusted:  # inside TRUSTED_PROXIES
        assert [attempt(trusted, "203.0.113.7") for _ in range(5)] == [401] * 5
        assert attempt(trusted, "203.0.113.7") == 429  # that client is blocked...
        assert attempt(trusted, "203.0.113.8") == 401  # ...but another client behind the same proxy is not

    limiter.reset()
    with TestClient(app, client=("8.8.8.8", 5000)) as untrusted:  # NOT a trusted proxy
        assert [attempt(untrusted, f"203.0.113.{i}") for i in range(5)] == [401] * 5
        # changing the header does not help: it is ignored, the real peer is counted
        assert attempt(untrusted, "198.51.100.1") == 429


def test_account_is_locked_after_too_many_failures(client):
    for _ in range(settings.login_max_failures):
        assert client.post("/login", json={"username": "manager_a", "password": "wrong"}).status_code == 401
    # Even the right password is refused now
    locked = client.post("/login", json={"username": "manager_a", "password": PASSWORD})
    assert locked.status_code == 429
    assert "Retry-After" in locked.headers
    # Other accounts are not affected
    assert client.post("/login", json={"username": "manager_b", "password": PASSWORD}).status_code == 200


def test_successful_login_resets_the_failure_count(client):
    for _ in range(settings.login_max_failures - 1):
        client.post("/login", json={"username": "manager_a", "password": "wrong"})
    assert client.post("/login", json={"username": "manager_a", "password": PASSWORD}).status_code == 200
    for _ in range(settings.login_max_failures - 1):
        client.post("/login", json={"username": "manager_a", "password": "wrong"})
    assert client.post("/login", json={"username": "manager_a", "password": PASSWORD}).status_code == 200


def test_lockout_unlocks_by_itself(client):
    for _ in range(settings.login_max_failures):
        client.post("/login", json={"username": "manager_a", "password": "wrong"})
    for attempts in login_guard._attempts.values():
        attempts.locked_until = 0  # time passes
    assert client.post("/login", json={"username": "manager_a", "password": PASSWORD}).status_code == 200


# ── Password change ──────────────────────────────────────────────────


def test_change_password(client, login):
    headers = login("employee_a")
    wrong = client.put("/profile/password", headers=headers, json={"currentPassword": "nope", "newPassword": "Newpass123"})
    assert wrong.status_code == 401

    weak = client.put("/profile/password", headers=headers, json={"currentPassword": PASSWORD, "newPassword": "abc"})
    assert weak.status_code == 400
    assert "At least 8 characters" in weak.json()["missing"]

    same = client.put("/profile/password", headers=headers, json={"currentPassword": PASSWORD, "newPassword": PASSWORD})
    assert same.json()["missing"] == ["Must be different from the previous one"]

    ok = client.put("/profile/password", headers=headers, json={"currentPassword": PASSWORD, "newPassword": "Newpass123"})
    assert ok.status_code == 200
    assert client.post("/login", json={"username": "employee_a", "password": PASSWORD}).status_code == 401
    assert client.post("/login", json={"username": "employee_a", "password": "Newpass123"}).status_code == 200
