"""The Casbin policy (app/authz/policy.csv) and how it is applied."""

from fastapi.routing import APIRoute

from app.authz import enforcer, is_allowed
from app.main import app
from tests.conftest import PASSWORD

PUBLIC = {("/", "GET"), ("/login", "POST"), ("/metrics", "GET")}  # no session needed: not in the policy
ROLES = ("employee", "manager", "director")


def _api_routes():
    found = set()
    for route in app.routes:
        members = route.original_router.routes if type(route).__name__ == "_IncludedRouter" else [route]
        for member in members:
            if isinstance(member, APIRoute):
                found.update((member.path_format, method) for method in member.methods)
    return found


def test_every_route_is_in_the_policy_or_public():
    """A new route without a policy line would answer 403 to everybody: catch it here."""
    routes = _api_routes()
    assert len(routes) > 40  # the walk really found the routes
    missing = [
        (path, method)
        for path, method in routes - PUBLIC
        if not any(is_allowed(role, path, method) for role in ROLES)
    ]
    assert missing == []


def test_policy_has_no_line_for_a_route_that_does_not_exist():
    routes = _api_routes()
    stale = [
        (obj, act) for _, obj, act in enforcer.get_policy() if (obj, act) not in routes
    ]
    assert stale == []


def test_policy_matrix():
    assert is_allowed("manager", "/rooms", "POST")
    assert not is_allowed("director", "/rooms", "POST")
    assert not is_allowed("employee", "/rooms", "POST")
    assert is_allowed("director", "/audit", "GET")
    assert not is_allowed("manager", "/audit", "GET")
    assert is_allowed("employee", "/time-records/clock-in", "POST")
    assert not is_allowed("director", "/time-records/clock-in", "POST")
    assert is_allowed("employee", "/profile", "GET")  # via the "authenticated" group
    assert is_allowed("director", "/profile", "GET")


def test_what_is_not_listed_is_denied():
    assert not is_allowed("director", "/does-not-exist", "GET")
    assert not is_allowed("director", "/rooms", "DELETE")
    assert not is_allowed("unknown-role", "/profile", "GET")
    assert not is_allowed("manager", "/staff/{other_name}", "GET")  # only the real template matches


def test_the_route_decides_not_the_url_text(client, login):
    """The check uses the route template, so /staff/1 and /staff/2 follow the same rule."""
    employee = login("employee_a")
    assert client.get("/staff/1", headers=employee).status_code == 403
    assert client.get("/staff/999999", headers=employee).status_code == 403  # 403, not 404: the role is checked first


def test_role_checked_after_token(client):
    assert client.get("/staff").status_code == 401  # no token: 401 before any role check


def test_denied_access_is_logged_as_security_event(client, login, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="app.security"):
        assert client.post("/rooms", headers=login("employee_a"), json={"name": "x", "minStaff": 1}).status_code == 403
    assert any("access_denied" in record.getMessage() for record in caplog.records)
    assert PASSWORD  # (imported so the fixtures' password stays the single source)
