"""Error format, logging (A09), metrics, headers and the exposure of sensitive data."""

import json
import logging

from app.logging_config import JsonFormatter, request_log
from tests.conftest import PASSWORD


# ── Error format ─────────────────────────────────────────────────────


def test_unknown_route_and_wrong_method(client, login):
    assert client.get("/nope").json() == {"error": "Route not found"}
    assert client.get("/nope").status_code == 404
    wrong = client.delete("/catalogs", headers=login("director"))
    assert wrong.status_code == 405
    assert wrong.json() == {"error": "Method not allowed"}


def test_validation_errors_have_one_format_and_do_not_echo_the_input(client, login):
    response = client.post(
        "/login", json={"username": 123, "password": "my-secret-password-xyz", "extra": 1}
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "Invalid data"
    assert {"in": "body", "field": "username", "message": "Input should be a valid string"} in body["details"]
    assert "my-secret-password-xyz" not in response.text


def test_invalid_json_and_invalid_ids(client, login):
    headers = {**login("director"), "Content-Type": "application/json"}
    broken = client.post("/catalogs/positions", headers=headers, content="{not json")
    assert broken.status_code == 400 and broken.json()["details"][0]["message"] == "The body is not valid JSON"
    bad_id = client.get("/staff/abc", headers=headers)
    assert bad_id.status_code == 400 and bad_id.json()["details"][0]["in"] == "path"
    assert client.get("/staff/99999", headers=headers).json() == {"error": "Not found"}


def test_unhandled_errors_are_a_generic_500_with_a_request_id(client, login, monkeypatch):
    import app.routers.catalogs as catalogs

    def boom(*args, **kwargs):
        raise RuntimeError("secret internals: password=hunter2")

    monkeypatch.setattr(catalogs, "_all", boom)
    response = client.get("/catalogs", headers=login("employee_a"))
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "Internal error" and body["requestId"] == response.headers["X-Request-ID"]
    assert "hunter2" not in response.text and "RuntimeError" not in response.text


def test_database_constraints_become_http_errors(client, login):
    headers = login("director")
    # CHECK constraint: a shift cannot be changed to invalid values on the API side, but latitude is checked by the DB too
    response = client.post("/daycares", headers=headers, json={"name": "X", "latitude": 95, "longitude": 0})
    assert response.status_code == 400


# ── Sensitive data ───────────────────────────────────────────────────


def test_password_hashes_never_leave_the_api(client, login, world):
    headers = login("director")
    for path in ("/staff?active=all", f"/staff/{world['ids']['employee_a']}", "/profile", "/attendance", "/schedules"):
        text = client.get(path, headers=headers).text.lower()
        assert "password" not in text and "$2b$" not in text and "hash" not in text, path


# ── Headers ──────────────────────────────────────────────────────────


def test_security_headers_and_request_id(client):
    response = client.get("/")
    assert response.json() == {"message": "Sonrisas de Cristal API is running"}
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert len(response.headers["X-Request-ID"]) == 12


# ── Logging (A09) ────────────────────────────────────────────────────


def event(events, name):
    return [e for e in events if e.get("event") == name]


def test_failed_login_is_logged_without_the_password(client, security_events):
    client.post("/login", json={"username": "manager_a", "password": "very-secret-guess"})
    client.post("/login", json={"username": "ghost", "password": "another-guess"})
    failed = event(security_events, "login_failed")
    assert [(e["username"], e["reason"]) for e in failed] == [("manager_a", "bad_password"), ("ghost", "unknown_user")]
    assert "very-secret-guess" not in json.dumps(security_events)
    assert "another-guess" not in json.dumps(security_events)


def test_successful_login_and_lockout_are_logged(client, security_events):
    from app.config import settings

    client.post("/login", json={"username": "manager_a", "password": PASSWORD})
    assert event(security_events, "login_success")[0]["role"] == "manager"
    for _ in range(settings.login_max_failures):
        client.post("/login", json={"username": "manager_b", "password": "wrong"})
    assert event(security_events, "account_locked")[0]["username"] == "manager_b"
    client.post("/login", json={"username": "manager_b", "password": PASSWORD})
    assert event(security_events, "login_locked")


def test_auth_failures_and_forbidden_access_are_logged(client, login, security_events):
    client.get("/profile")
    client.get("/profile", headers={"Authorization": "Bearer junk"})
    client.get("/staff", headers=login("employee_a"))
    names = [e["event"] for e in security_events]
    assert "auth_missing_token" in names and "auth_invalid_token" in names
    denied = event(security_events, "access_denied")[0]
    assert denied["role"] == "employee" and denied["path"] == "/staff" and denied["allowed"] == ["manager", "director"]
    assert "ip" in denied and "user_id" in denied


def test_staff_changes_are_logged_with_who_and_whom(client, login, world, security_events):
    director = login("director")
    person = world["ids"]["employee_a"]
    client.put(f"/staff/{person}", headers=director, json={"role": "manager"})
    client.post(f"/staff/{person}/password", headers=login("manager_a"))
    client.put("/profile/password", headers=login("employee_b"), json={"currentPassword": PASSWORD, "newPassword": "Newpass123"})
    changed = event(security_events, "role_changed")[0]
    assert (changed["previous_role"], changed["new_role"], changed["by_user_id"], changed["target_user_id"]) == (
        "employee", "manager", world["ids"]["director"], person,
    )
    assert event(security_events, "password_changed")[0]["user_id"] == world["ids"]["employee_b"]
    # the reset was refused for a manager acting on another manager, so it is an access problem, not a reset
    assert event(security_events, "password_reset") == []


def test_every_request_is_logged_with_user_status_and_time(client, login, world):
    lines: list[dict] = []

    class Collector(logging.Handler):
        def emit(self, record):
            lines.append(record.fields)

    handler = Collector()
    request_log.addHandler(handler)
    try:
        headers = login("manager_a")
        client.get("/staff", headers=headers)
        client.get("/staff/999999", headers=headers)
    finally:
        request_log.removeHandler(handler)
    staff = [line for line in lines if line["path"] == "/staff"][0]
    assert staff["method"] == "GET" and staff["status"] == 200
    assert staff["user_id"] == world["ids"]["manager_a"]
    assert staff["duration_ms"] >= 0 and staff["request_id"] and staff["ip"]
    assert [line["status"] for line in lines if line["path"] == "/staff/999999"] == [404]


def test_log_lines_are_json_and_cannot_be_forged(client):
    record = logging.LogRecord("app.security", logging.WARNING, __file__, 1, "login_failed", None, None)
    record.fields = {"username": 'bob"\n{"level": "CRITICAL", "message": "forged"}'}
    line = JsonFormatter().format(record)
    assert "\n" not in line  # one event, one line
    assert json.loads(line)["level"] == "WARNING"


# ── Metrics ──────────────────────────────────────────────────────────


def test_metrics_need_the_token(client, login):
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # a normal user token is not the metrics token
    assert client.get("/metrics", headers=login("director")).status_code == 401


def test_metrics_content(client, login):
    client.get("/staff", headers=login("manager_a"))
    client.get("/staff/12345", headers=login("manager_a"))
    response = client.get("/metrics", headers={"Authorization": "Bearer metrics-test-token"})
    assert response.status_code == 200
    text = response.text
    assert 'http_requests_total{method="GET",route="/staff",status="200"}' in text
    # routes are labelled with their template, so ids do not create a series each
    assert 'route="/staff/{user_id}"' in text and "12345" not in text
    assert "http_request_duration_seconds_bucket" in text
    assert "db_pool_connections" in text


def test_metrics_are_off_without_a_token(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "metrics_token", None)
    assert client.get("/metrics").status_code == 404
