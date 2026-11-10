"""Roles (RBAC) and isolation between daycares (OWASP A01)."""

from datetime import timedelta

from app.timeutils import today
from tests.conftest import PASSWORD


def usernames(response):
    return {person["username"] for person in response.json()}


# ── Roles ────────────────────────────────────────────────────────────


def test_every_route_needs_a_token(client, world):
    protected = [
        ("GET", "/catalogs"), ("GET", "/daycares"), ("GET", "/rooms"), ("GET", "/staff"), ("GET", "/movements"),
        ("GET", "/schedules"), ("GET", "/time-records"), ("GET", "/corrections"), ("GET", "/attendance"),
        ("GET", "/notices"), ("GET", "/audit"), ("GET", "/coverage"), ("GET", "/summary"),
        ("GET", "/statistics"), ("GET", "/export/attendance"), ("GET", "/profile"),
        ("POST", "/time-records/clock-in"), ("POST", "/staff"), ("PUT", "/profile/password"),
    ]
    for method, path in protected:
        assert client.request(method, path).status_code == 401, (method, path)


def test_employee_is_blocked_from_management_routes(client, login):
    headers = login("employee_a")
    for method, path in [
        ("GET", "/staff"), ("GET", "/movements"), ("GET", "/schedules"), ("GET", "/notices"), ("GET", "/audit"),
        ("GET", "/coverage"), ("GET", "/summary"), ("GET", "/statistics"), ("GET", "/export/attendance"),
        ("GET", "/attendance"), ("POST", "/staff"), ("POST", "/rooms"), ("POST", "/notices"),
        ("POST", "/catalogs/positions"), ("POST", "/daycares"),
    ]:
        response = client.request(method, path, headers=headers, json={} if method == "POST" else None)
        assert response.status_code == 403, (method, path, response.status_code)
        assert response.json() == {"error": "Your role cannot do this"}


def test_manager_cannot_use_director_routes(client, login):
    headers = login("manager_a")
    assert client.get("/audit", headers=headers).status_code == 403
    assert client.get("/summary", headers=headers).status_code == 403
    assert client.post("/catalogs/positions", headers=headers, json={"name": "Cocina"}).status_code == 403
    assert client.post("/daycares", headers=headers, json={"name": "X", "latitude": 1, "longitude": 1}).status_code == 403


def test_director_cannot_use_manager_only_routes(client, login, world):
    headers = login("director")
    assert client.post("/rooms", headers=headers, json={"name": "Nueva", "minStaff": 1}).status_code == 403
    assert client.post("/attendance", headers=headers, json={}).status_code == 403
    assert client.post("/time-records/batch", headers=headers, json={"userIds": [1]}).status_code == 403


def test_director_creates_catalog_entries(client, login):
    headers = login("director")
    created = client.post("/catalogs/positions", headers=headers, json={"name": "Cocina"})
    assert created.status_code == 201
    names = [item["name"] for item in client.get("/catalogs", headers=headers).json()["positions"]]
    assert "Cocina" in names
    duplicate = client.post("/catalogs/absence-reasons", headers=headers, json={"description": "enfermedad"})
    assert duplicate.status_code == 409


def test_catalogs_use_english_role_names(client, login):
    roles = client.get("/catalogs", headers=login("employee_a")).json()["roles"]
    assert sorted(role["name"] for role in roles) == ["director", "employee", "manager"]


# ── Isolation between daycares ───────────────────────────────────────


def test_manager_sees_only_their_daycare(client, login):
    assert usernames(client.get("/staff", headers=login("manager_a"))) == {"manager_a", "employee_a"}
    assert usernames(client.get("/staff", headers=login("manager_b"))) == {"manager_b", "employee_b"}


def test_manager_cannot_pick_another_daycare_with_a_query_parameter(client, login, world):
    response = client.get(f"/staff?daycareId={world['daycare_b']}", headers=login("manager_a"))
    assert usernames(response) == {"manager_a", "employee_a"}  # the parameter is ignored


def test_director_sees_everyone_and_can_filter(client, login, world):
    headers = login("director")
    assert usernames(client.get("/staff", headers=headers)) == {"director", "manager_a", "employee_a", "manager_b", "employee_b"}
    assert usernames(client.get(f"/staff?daycareId={world['daycare_b']}", headers=headers)) == {"manager_b", "employee_b"}


def test_other_daycare_is_404_not_403(client, login, world):
    manager = login("manager_a")
    other = world["ids"]["employee_b"]
    for method, path, body in [
        ("GET", f"/staff/{other}", None),
        ("PUT", f"/staff/{other}", {"name": "Hacked"}),
        ("POST", f"/staff/{other}/terminate", {"terminationReasonId": 1}),
        ("POST", f"/staff/{other}/password", None),
        ("GET", f"/schedules/{other}", None),
        ("PUT", f"/schedules/{other}", {"days": []}),
        ("GET", f"/attendance/{other}", None),
        ("GET", f"/rooms/{world['room_b']}", None),
        ("PUT", f"/rooms/{world['room_b']}", {"name": "Hacked"}),
        ("POST", "/attendance", {"userId": other, "date": str(today()), "status": "present"}),
    ]:
        response = client.request(method, path, headers=manager, json=body)
        assert response.status_code == 404, (method, path, response.status_code, response.text)


def test_manager_never_sees_directors(client, login, world):
    manager = login("manager_a")
    assert client.get(f"/staff/{world['ids']['director']}", headers=manager).status_code == 404
    assert "director" not in usernames(client.get("/staff?active=all", headers=manager))


def test_manager_cannot_modify_another_manager(client, login, world):
    director = login("director")
    created = client.post(
        "/staff",
        headers=director,
        json={
            "name": "Second Manager", "username": "manager_a2", "email": "m2@example.com", "phone": "81",
            "positionId": world["position"], "role": "manager", "daycareId": world["daycare_a"],
        },
    )
    assert created.status_code == 201, created.text
    other_manager = created.json()["id"]
    manager = login("manager_a")
    assert client.put(f"/staff/{other_manager}", headers=manager, json={"name": "X"}).status_code == 403
    assert client.post(f"/staff/{other_manager}/password", headers=manager).status_code == 403
    assert client.post(f"/staff/{other_manager}/terminate", headers=manager, json={"terminationReasonId": 1}).status_code == 403
    # A director can
    assert client.put(f"/staff/{other_manager}", headers=director, json={"name": "Renamed"}).status_code == 200


def test_manager_cannot_set_role_or_daycare(client, login, world):
    manager = login("manager_a")
    body = {"name": "N", "username": "n1", "email": "n1@example.com", "phone": "81", "positionId": world["position"]}
    assert client.post("/staff", headers=manager, json={**body, "role": "manager"}).status_code == 403
    assert client.post("/staff", headers=manager, json={**body, "daycareId": world["daycare_b"]}).status_code == 403
    assert client.put(f"/staff/{world['ids']['employee_a']}", headers=manager, json={"role": "director"}).status_code == 403


def test_extra_fields_are_rejected(client, login, world):
    """No mass assignment: a field the endpoint does not declare is an error, not silently saved."""
    response = client.put(
        f"/staff/{world['ids']['employee_a']}", headers=login("manager_a"), json={"name": "Ok", "isActive": False, "roleId": 3}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Invalid data"


def test_records_of_other_daycares_are_not_listed(client, login, world):
    day = str(today() - timedelta(days=1))
    for who in ("employee_a", "employee_b"):
        r = client.post("/time-records/clock-in", headers=login(who), json={"occurredAt": f"{day}T07:00:00"})
        assert r.status_code == 201, r.text
    listed = client.get(f"/time-records?startDate={day}&endDate={day}", headers=login("manager_a")).json()
    assert {item["user"]["id"] for item in listed} == {world["ids"]["employee_a"]}
    # employees only see their own
    mine = client.get(f"/time-records?startDate={day}&endDate={day}", headers=login("employee_b")).json()
    assert {item["user"]["id"] for item in mine} == {world["ids"]["employee_b"]}


def test_notices_and_corrections_are_scoped(client, login, world):
    manager_a, manager_b = login("manager_a"), login("manager_b")
    notice = client.post("/notices", headers=manager_b, json={"subject": "S", "message": "M", "noticeType": "reminder"})
    assert notice.status_code == 201
    assert client.get(f"/notices/{notice.json()['id']}", headers=manager_a).status_code == 404
    assert client.get("/notices", headers=manager_a).json() == []


# ── Staff lifecycle ──────────────────────────────────────────────────


def test_manager_hires_an_employee(client, login, world):
    manager = login("manager_a")
    response = client.post(
        "/staff",
        headers=manager,
        json={"name": "Nueva Persona", "username": "nueva", "email": "nueva@example.com", "phone": "81", "positionId": world["position"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"]["name"] == "employee"
    assert body["daycareId"] == world["daycare_a"]
    assert "passwordHash" not in body and "password" not in body
    # The temporary password works once, and the hire is in the history
    login_response = client.post("/login", json={"username": "nueva", "password": body["temporaryPassword"]})
    assert login_response.status_code == 200
    movements = client.get("/movements", headers=manager).json()
    assert [(m["type"], m["user"]["name"]) for m in movements] == [("hire", "Nueva Persona")]


def test_duplicate_username_is_409(client, login, world):
    manager = login("manager_a")
    body = {"name": "N", "username": "employee_a", "email": "other@example.com", "phone": "81", "positionId": world["position"]}
    response = client.post("/staff", headers=manager, json=body)
    assert response.status_code == 409
    assert "already exists" in response.json()["error"]


def test_weak_initial_password_is_rejected(client, login, world):
    body = {"name": "N", "username": "n2", "email": "n2@example.com", "phone": "81", "positionId": world["position"], "password": "abc"}
    response = client.post("/staff", headers=login("manager_a"), json=body)
    assert response.status_code == 400
    assert response.json()["missing"]


def test_password_reset_returns_a_working_temporary_password(client, login, world):
    response = client.post(f"/staff/{world['ids']['employee_a']}/password", headers=login("manager_a"))
    assert response.status_code == 200
    temporary = response.json()["temporaryPassword"]
    assert len(temporary) == 8
    assert client.post("/login", json={"username": "employee_a", "password": temporary}).status_code == 200
    assert client.post("/login", json={"username": "employee_a", "password": PASSWORD}).status_code == 401


def test_terminate_keeps_the_history_and_blocks_a_second_time(client, login, world):
    manager = login("manager_a")
    person = world["ids"]["employee_a"]
    assert client.post(f"/staff/{person}/terminate", headers=manager, json={"terminationReasonId": 1}).status_code == 200
    assert client.post(f"/staff/{person}/terminate", headers=manager, json={"terminationReasonId": 1}).status_code == 409
    assert "employee_a" not in usernames(client.get("/staff", headers=manager))
    assert "employee_a" in usernames(client.get("/staff?active=false", headers=manager))
    detail = client.get(f"/staff/{person}", headers=manager).json()
    assert [m["type"] for m in detail["movements"]] == ["termination", "hire"]


def test_nobody_terminates_themselves(client, login, world):
    response = client.post(f"/staff/{world['ids']['manager_a']}/terminate", headers=login("manager_a"), json={"terminationReasonId": 1})
    # a manager cannot touch another manager at all; a director terminating themselves is refused too
    assert response.status_code == 403
    director = client.post(f"/staff/{world['ids']['director']}/terminate", headers=login("director"), json={"terminationReasonId": 1})
    assert director.status_code == 400
    assert director.json() == {"error": "You cannot terminate yourself"}


def test_transfer_validations(client, login, world):
    director = login("director")
    person = world["ids"]["employee_a"]
    same = client.post(f"/staff/{person}/transfer", headers=director, json={"daycareId": world["daycare_a"]})
    assert same.status_code == 400
    missing = client.post(f"/staff/{person}/transfer", headers=director, json={"daycareId": 999})
    assert missing.status_code == 400
    ok = client.post(f"/staff/{person}/transfer", headers=director, json={"daycareId": world["daycare_b"], "notes": "Closer to home"})
    assert ok.status_code == 200
    moves = client.get(f"/movements?type=transfer&daycareId={world['daycare_b']}", headers=director).json()
    assert len(moves) == 1 and moves[0]["notes"] == "Closer to home"
