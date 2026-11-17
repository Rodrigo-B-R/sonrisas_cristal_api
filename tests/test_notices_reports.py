"""Notices, rooms, schedules, coverage and reports."""

from datetime import timedelta

from app.routers.reports import _safe_cell
from app.timeutils import today


# ── Notices ──────────────────────────────────────────────────────────


def test_notice_reaches_the_daycare_and_can_be_confirmed(client, login, world):
    manager, employee = login("manager_a"), login("employee_a")
    created = client.post(
        "/notices", headers=manager,
        json={"subject": "Meeting", "message": "Friday at 3", "noticeType": "meeting", "requiresConfirmation": True},
    )
    assert created.status_code == 201, created.text
    notice = created.json()
    # Only the active non-director people of the daycare, never the author
    assert notice["recipientCount"] == 1 and notice["confirmedCount"] == 0
    assert notice["noticeType"] == "meeting" and notice["requiresConfirmation"] is True
    assert notice["daycareId"] == world["daycare_a"]

    inbox = client.get("/notices/inbox", headers=employee).json()
    assert [(n["id"], n["read"], n["readAt"]) for n in inbox] == [(notice["id"], False, None)]
    assert client.get("/notices/inbox", headers=login("employee_b")).json() == []

    read = client.post(f"/notices/{notice['id']}/read", headers=employee)
    assert read.status_code == 200 and read.json()["read"] is True
    first_time = read.json()["readAt"]
    assert client.post(f"/notices/{notice['id']}/read", headers=employee).json()["readAt"] == first_time  # the first time stays

    detail = client.get(f"/notices/{notice['id']}", headers=manager).json()
    assert detail["recipientCount"] == 1
    assert [p["name"] for p in detail["confirmed"]] == ["Employee A"] and detail["pending"] == []
    assert client.get("/notices", headers=manager).json()[0]["confirmedCount"] == 1


def test_a_notice_is_not_for_everyone(client, login, world):
    notice = client.post("/notices", headers=login("manager_a"), json={"subject": "S", "message": "M", "noticeType": "urgent"}).json()
    assert client.post(f"/notices/{notice['id']}/read", headers=login("employee_b")).status_code == 404
    assert client.get(f"/notices/inbox/{notice['id']}", headers=login("employee_b")).status_code == 404
    assert client.get(f"/notices/inbox/{notice['id']}", headers=login("employee_a")).status_code == 200


def test_notice_to_specific_people_stays_inside_the_daycare(client, login, world):
    ids = world["ids"]
    response = client.post(
        "/notices", headers=login("manager_a"),
        json={"subject": "S", "message": "M", "noticeType": "reminder", "target": "people", "userIds": [ids["employee_a"], ids["employee_b"]]},
    )
    assert response.status_code == 201
    assert response.json()["recipientCount"] == 1  # employee_b is from another daycare: ignored
    nobody = client.post(
        "/notices", headers=login("manager_a"),
        json={"subject": "S", "message": "M", "noticeType": "reminder", "target": "people", "userIds": [ids["employee_b"]]},
    )
    assert nobody.status_code == 400


def test_notice_to_a_shift_and_a_room(client, login, world):
    manager = login("manager_a")
    base = {"subject": "S", "message": "M", "noticeType": "reminder"}
    morning = client.post("/notices", headers=manager, json={**base, "target": "shift", "shiftId": world["morning"]})
    assert morning.json()["recipientCount"] == 1  # employee_a works the morning shift
    evening = client.post("/notices", headers=manager, json={**base, "target": "shift", "shiftId": world["evening"]})
    assert evening.status_code == 400  # nobody
    room = client.post("/notices", headers=manager, json={**base, "target": "room", "roomId": world["room_a"]})
    assert room.json()["recipientCount"] == 1
    assert client.post("/notices", headers=manager, json={**base, "target": "shift"}).status_code == 400


def test_general_notice_from_a_director(client, login, world):
    director, manager_a = login("director"), login("manager_a")
    general = client.post("/notices", headers=director, json={"subject": "All", "message": "Holiday", "noticeType": "reminder"})
    assert general.status_code == 201, general.text
    assert general.json()["daycareId"] is None
    assert general.json()["recipientCount"] == 4  # both managers and both employees
    # A manager only counts the readers of their own daycare
    seen = client.get("/notices", headers=manager_a).json()
    assert [(n["subject"], n["recipientCount"]) for n in seen] == [("All", 2)]
    assert len(client.get("/notices/inbox", headers=manager_a).json()) == 1  # and received it too
    assert seen[0]["read"] is False
    # A director can aim at one daycare
    one = client.post("/notices", headers=director, json={"subject": "B", "message": "Only B", "noticeType": "reminder", "daycareId": world["daycare_b"]})
    assert one.json()["recipientCount"] == 2


def test_manager_cannot_write_to_another_daycare(client, login, world):
    response = client.post(
        "/notices", headers=login("manager_a"),
        json={"subject": "S", "message": "M", "noticeType": "reminder", "daycareId": world["daycare_b"]},
    )
    assert response.status_code == 403


def test_notice_validations(client, login):
    manager = login("manager_a")
    assert client.post("/notices", headers=manager, json={"subject": "S", "message": "M" * 256, "noticeType": "reminder"}).status_code == 400
    assert client.post("/notices", headers=manager, json={"subject": "S", "message": "M", "noticeType": "nope"}).status_code == 400


# ── Rooms and schedules ──────────────────────────────────────────────


def test_rooms(client, login, world):
    manager = login("manager_a")
    created = client.post("/rooms", headers=manager, json={"name": "Preescolar", "minStaff": 4})
    assert created.status_code == 201 and created.json()["daycareId"] == world["daycare_a"]
    assert client.put(f"/rooms/{created.json()['id']}", headers=manager, json={"minStaff": 5}).json()["minStaff"] == 5
    assert client.post("/rooms", headers=manager, json={"name": "X", "minStaff": -1}).status_code == 400
    # An employee sees the rooms of their daycare only
    assert {r["daycareId"] for r in client.get("/rooms", headers=login("employee_a")).json()} == {world["daycare_a"]}


def test_replace_a_schedule_closes_the_old_one(client, login, world):
    manager, person = login("manager_a"), world["ids"]["employee_a"]
    start = str(today() + timedelta(days=7))
    new = client.put(
        f"/schedules/{person}", headers=manager,
        json={"validFrom": start, "days": [{"day": "monday", "shiftId": world["evening"], "roomId": world["room_a"]}]},
    )
    assert new.status_code == 201, new.text
    assert new.json()["validFrom"] == start and new.json()["validUntil"] == "2099-12-31"
    assert new.json()["days"][0]["weekday"] == "monday"
    # Before that date the old one still counts, after it the new one
    before = client.get(f"/schedules/{person}", headers=manager).json()["schedule"]
    assert len(before["days"]) == 7
    after = client.get(f"/schedules/{person}?date={start}", headers=manager).json()["schedule"]
    assert [d["weekday"] for d in after["days"]] == ["monday"]
    assert client.get("/schedules/me", headers=login("employee_a")).json()["days"][0]["shift"]["name"] == "matutino"


def test_schedule_validations(client, login, world):
    manager, person = login("manager_a"), world["ids"]["employee_a"]
    day = {"day": "monday", "shiftId": world["morning"], "roomId": world["room_a"]}
    assert client.put(f"/schedules/{person}", headers=manager, json={"days": [day, day]}).status_code == 400  # repeated
    assert client.put(f"/schedules/{person}", headers=manager, json={"days": [{**day, "roomId": world["room_b"]}]}).status_code == 400
    assert client.put(f"/schedules/{person}", headers=manager, json={"days": [{**day, "shiftId": 999}]}).status_code == 400
    assert client.put(f"/schedules/{person}", headers=manager, json={"days": [{**day, "day": "lunes"}]}).status_code == 400
    assert client.put(f"/schedules/{person}", headers=manager, json={"days": []}).status_code == 201  # all days off


def test_schedules_list(client, login, world):
    rows = client.get("/schedules", headers=login("manager_a")).json()
    assert [r["person"]["name"] for r in rows] == ["Employee A", "Manager A"]
    assert rows[1]["schedule"] is None


# ── Coverage and reports ─────────────────────────────────────────────


def test_coverage(client, login, world):
    day = str(today() - timedelta(days=1))
    report = client.get(f"/coverage?date={day}", headers=login("manager_a")).json()
    assert report["daycare"]["name"] == "Cumbres" and report["scheduled"] == 1 and report["present"] == 0
    lactantes = report["rooms"][0]
    assert lactantes["room"]["name"] == "Lactantes" and lactantes["minimum"] == 1
    morning = lactantes["shifts"][0]
    assert (morning["scheduled"], morning["present"], morning["started"], morning["missing"]) == (1, 0, True, 1)
    assert report["complete"] is False
    assert "Missing 1 in Lactantes (matutino)" in report["alerts"]
    # After the employee clocks in, that gap closes (Maternal is still short: nobody scheduled)
    client.post("/time-records/clock-in", headers=login("employee_a"), json={"occurredAt": f"{day}T07:00:00"})
    report = client.get(f"/coverage?date={day}", headers=login("manager_a")).json()
    assert report["present"] == 1 and report["rooms"][0]["shifts"][0]["missing"] == 0
    assert report["alerts"] == [
        "Missing 1 in Lactantes (vespertino)",
        "Missing 1 in Maternal (matutino)",
        "Missing 1 in Maternal (vespertino)",
    ]


def test_coverage_needs_a_daycare_for_directors(client, login, world):
    director = login("director")
    assert client.get("/coverage", headers=director).status_code == 400
    assert client.get(f"/coverage?daycareId={world['daycare_b']}", headers=director).json()["daycare"]["name"] == "Apodaca"
    assert client.get("/coverage?daycareId=999", headers=director).status_code == 404


def test_summary(client, login):
    body = client.get("/summary", headers=login("director")).json()
    assert body["completeCount"] + body["understaffedCount"] == 2
    assert {d["name"] for d in body["daycares"]} == {"Cumbres", "Apodaca"}


def test_statistics(client, login, world):
    body = client.get("/statistics", headers=login("manager_a")).json()
    assert [d["daycare"]["name"] for d in body["byDaycare"]] == ["Cumbres"]  # a manager only gets their own
    assert set(body) >= {"startDate", "endDate", "hires", "terminations", "absences", "lates", "understaffedDays", "absenteeism"}
    director = client.get("/statistics?startDate=2019-12-01&endDate=2020-01-31", headers=login("director")).json()
    assert director["hires"] == 5  # the hires of the test data, on 2020-01-01
    assert len(director["byDaycare"]) == 2


def test_export_csv(client, login):
    day = str(today() - timedelta(days=1))
    client.post("/time-records/clock-in", headers=login("employee_a"), json={"occurredAt": f"{day}T07:20:00"})
    response = client.get(f"/export/attendance?startDate={day}&endDate={day}", headers=login("manager_a"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f"attendance_{day}_{day}.csv" in response.headers["content-disposition"]
    text = response.content.decode("utf-8-sig")  # the BOM is for Excel
    lines = text.strip().split("\r\n")
    assert lines[0].startswith('"daycare","name","username"')
    assert '"Employee A"' in lines[1] and '"late"' in lines[1] and '"07:00-15:00"' in lines[1]
    assert "Employee B" not in text  # another daycare


def test_csv_cells_cannot_run_as_formulas():
    assert _safe_cell("=HYPERLINK(\"http://evil\")") == "'=HYPERLINK(\"http://evil\")"
    assert _safe_cell("+1+1") == "'+1+1"
    assert _safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert _safe_cell("Ana Torres") == "Ana Torres"
    assert _safe_cell(None) == ""
    assert _safe_cell(0) == "0"


# ── Audit (the triggers are not here: on SQLite it is just an empty table) ──


def test_audit_is_for_directors_and_validates_the_table(client, login):
    assert client.get("/audit", headers=login("director")).json() == []
    assert client.get("/audit?table=usuario", headers=login("director")).status_code == 400
    assert client.get("/audit?table=asistencia", headers=login("director")).status_code == 200
