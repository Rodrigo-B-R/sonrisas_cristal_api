"""Clock-in / clock-out, attendance and manager fixes."""

import uuid
from datetime import timedelta

from app.timeutils import today

YESTERDAY = today() - timedelta(days=1)
DAY = str(YESTERDAY)


def clock_in(client, headers, time="07:02:00", **extra):
    return client.post("/time-records/clock-in", headers=headers, json={"occurredAt": f"{DAY}T{time}", **extra})


# ── Clock-in ─────────────────────────────────────────────────────────


def test_clock_in_uses_the_schedule_and_marks_present(client, login, world):
    response = clock_in(client, login("employee_a"))
    assert response.status_code == 201, response.text
    body = response.json()
    record = body["record"]
    assert record["shift"]["name"] == "matutino"
    assert record["shift"]["startTime"] == "07:00"
    assert record["roomId"] == world["room_a"]
    assert record["source"] == "app"
    assert record["withinZone"] is True
    # 07:02 in Monterrey (UTC-6) is 13:02 UTC, and times come out as UTC with milliseconds
    assert record["clockInAt"] == f"{DAY}T13:02:00.000Z"
    assert record["clockOutAt"] is None
    assert body["attendance"]["status"] == "present"
    assert body["repeated"] is False


def test_arriving_after_the_tolerance_is_late(client, login):
    body = clock_in(client, login("employee_a"), time="07:20:00").json()
    assert body["attendance"]["status"] == "late"


def test_arriving_within_the_tolerance_is_present(client, login):
    assert clock_in(client, login("employee_a"), time="07:05:00").json()["attendance"]["status"] == "present"
    # The same day, 6 minutes late is late (tolerance 5)
    assert clock_in(client, login("employee_b"), time="07:06:00").json()["attendance"]["status"] == "late"


def test_same_uuid_is_not_duplicated(client, login):
    headers = login("employee_a")
    key = str(uuid.uuid4())
    first = clock_in(client, headers, uuid=key)
    second = clock_in(client, headers, uuid=key)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["repeated"] is True
    assert second.json()["record"]["id"] == first.json()["record"]["id"]
    listed = client.get(f"/time-records?startDate={DAY}&endDate={DAY}", headers=headers).json()
    assert len(listed) == 1


def test_uuid_of_another_person_is_a_conflict(client, login):
    key = str(uuid.uuid4())
    assert clock_in(client, login("employee_a"), uuid=key).status_code == 201
    other = clock_in(client, login("employee_b"), uuid=key)
    assert other.status_code == 409
    assert other.json() == {"error": "That uuid was already used"}


def test_second_clock_in_needs_a_clock_out_first(client, login):
    headers = login("employee_a")
    assert clock_in(client, headers).status_code == 201
    again = clock_in(client, headers, time="08:00:00")
    assert again.status_code == 409
    assert "clock out first" in again.json()["error"]


def test_clock_in_without_a_schedule_needs_room_and_shift(client, login, world):
    manager = login("manager_a")  # managers have no schedule in the test data
    response = clock_in(client, manager)
    assert response.status_code == 400
    assert "roomId and shiftId" in response.json()["error"]
    ok = clock_in(client, manager, roomId=world["room_a"], shiftId=world["evening"], time="12:00:00")
    assert ok.status_code == 201
    assert ok.json()["record"]["shift"]["name"] == "vespertino"


def test_room_of_another_daycare_is_refused(client, login, world):
    response = clock_in(client, login("manager_a"), roomId=world["room_b"], shiftId=world["morning"])
    assert response.status_code == 400


def test_room_and_shift_go_together(client, login, world):
    response = clock_in(client, login("employee_a"), roomId=world["room_a"])
    assert response.status_code == 400
    assert response.json() == {"error": "Send both roomId and shiftId, or neither"}


def test_future_time_is_refused(client, login):
    future = (today() + timedelta(days=2)).isoformat()
    response = client.post("/time-records/clock-in", headers=login("employee_a"), json={"occurredAt": f"{future}T08:00:00"})
    assert response.status_code == 400
    assert "future" in response.json()["error"]


def test_position_decides_within_zone(client, login):
    near = clock_in(client, login("employee_a"), latitude=25.7447, longitude=-100.4).json()["record"]
    far = clock_in(client, login("employee_b"), latitude=20.0, longitude=-100.4).json()["record"]
    assert near["withinZone"] is True
    assert far["withinZone"] is False  # saved anyway, for the manager to review
    flagged = client.get(f"/time-records?startDate={DAY}&endDate={DAY}&withinZone=false", headers=login("manager_b")).json()
    assert [item["id"] for item in flagged] == [far["id"]]


def test_invalid_coordinates_are_rejected(client, login):
    response = clock_in(client, login("employee_a"), latitude=999, longitude=0)
    assert response.status_code == 400


# ── Clock-out ────────────────────────────────────────────────────────


def test_clock_out(client, login):
    headers = login("employee_a")
    clock_in(client, headers)
    out = client.post("/time-records/clock-out", headers=headers, json={"occurredAt": f"{DAY}T15:00:00"})
    assert out.status_code == 200, out.text
    assert out.json()["clockOutAt"] == f"{DAY}T21:00:00.000Z"
    status = client.get("/time-records/status", headers=headers).json()
    assert status["inside"] is False


def test_clock_out_needs_an_open_entry(client, login):
    response = client.post("/time-records/clock-out", headers=login("employee_a"), json={})
    assert response.status_code == 409
    assert response.json() == {"error": "There is no open entry"}


def test_clock_out_before_clock_in_is_refused(client, login):
    headers = login("employee_a")
    clock_in(client, headers, time="08:00:00")
    response = client.post("/time-records/clock-out", headers=headers, json={"occurredAt": f"{DAY}T07:00:00"})
    assert response.status_code == 400


def test_clock_out_in_the_same_second_is_saved_one_second_later(client, login):
    headers = login("employee_a")
    clock_in(client, headers, time="08:00:00")
    out = client.post("/time-records/clock-out", headers=headers, json={"occurredAt": f"{DAY}T08:00:00"})
    assert out.status_code == 200
    assert out.json()["clockOutAt"] == f"{DAY}T14:00:01.000Z"


def test_status_screen(client, login, world):
    headers = login("employee_a")
    before = client.get("/time-records/status", headers=headers).json()
    assert before["inside"] is False and before["openRecord"] is None
    assert len(before["todayShifts"]) == 1
    assert before["location"]["radiusMeters"] == 150
    clock_in(client, headers)
    assert client.get("/time-records/status", headers=headers).json()["inside"] is True


# ── Batch (the manager clocks in several people) ─────────────────────


def test_batch_clock_in(client, login, world):
    ids = world["ids"]
    response = client.post(
        "/time-records/batch",
        headers=login("manager_a"),
        json={"userIds": [ids["employee_a"], ids["employee_b"], 9999], "occurredAt": f"{DAY}T07:00:00"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert [r["userId"] for r in body["recorded"]] == [ids["employee_a"]]
    assert body["recorded"][0]["source"] == "manager"
    assert {item["userId"] for item in body["skipped"]} == {ids["employee_b"], 9999}  # not in this daycare


def test_batch_skips_people_already_inside(client, login, world):
    ids = world["ids"]
    clock_in(client, login("employee_a"))
    response = client.post(
        "/time-records/batch", headers=login("manager_a"), json={"userIds": [ids["employee_a"]], "occurredAt": f"{DAY}T08:00:00"}
    )
    assert response.json()["recorded"] == []
    assert "open entry" in response.json()["skipped"][0]["reason"]


# ── Attendance ───────────────────────────────────────────────────────


def test_my_attendance_shows_the_day(client, login):
    headers = login("employee_a")
    clock_in(client, headers, time="07:20:00")
    client.post("/time-records/clock-out", headers=headers, json={"occurredAt": f"{DAY}T15:00:00"})
    report = client.get(f"/attendance/me?startDate={DAY}&endDate={DAY}", headers=headers).json()
    day = report["days"][0]
    assert (day["status"], day["clockIn"], day["clockOut"], day["lateMinutes"]) == ("late", "07:20", "15:00", 20)
    assert day["shifts"][0]["room"]["name"] == "Lactantes"
    assert report["summary"] == {"workedDays": 1, "lates": 1, "absences": 0, "incidents": 0}
    assert report["startDate"] == DAY


def test_a_day_with_a_shift_and_no_record_counts_as_absence(client, login):
    report = client.get(f"/attendance/me?startDate={DAY}&endDate={DAY}", headers=login("employee_a")).json()
    assert report["days"][0]["status"] == "no_record"
    assert report["summary"]["absences"] == 1


def test_manager_marks_an_absence_and_needs_a_reason(client, login, world):
    manager = login("manager_a")
    person = world["ids"]["employee_a"]
    no_reason = client.post("/attendance", headers=manager, json={"userId": person, "date": DAY, "status": "absent"})
    assert no_reason.status_code == 400
    assert [o["description"] for o in no_reason.json()["options"]] == ["enfermedad", "permiso"]

    bad = client.post("/attendance", headers=manager, json={"userId": person, "date": DAY, "status": "absent", "absenceReason": "nope"})
    assert bad.status_code == 400

    ok = client.post("/attendance", headers=manager, json={"userId": person, "date": DAY, "status": "absent", "absenceReason": "enfermedad"})
    assert ok.status_code == 201
    assert ok.json()["status"] == "absent" and ok.json()["absenceReason"]["description"] == "enfermedad"

    # A second POST for the same day corrects it (200 instead of 201)
    fixed = client.post("/attendance", headers=manager, json={"userId": person, "date": DAY, "status": "present"})
    assert fixed.status_code == 200
    assert fixed.json()["id"] == ok.json()["id"] and fixed.json()["absenceReason"] is None


def test_attendance_report_of_the_daycare(client, login, world):
    manager = login("manager_a")
    clock_in(client, login("employee_a"))
    report = client.get(f"/attendance?startDate={DAY}&endDate={DAY}", headers=manager).json()
    rows = {row["person"]["username"]: row for row in report}
    assert set(rows) == {"employee_a", "manager_a"}  # everyone employed in the period, directors excluded
    assert rows["employee_a"]["person"]["role"]["name"] == "employee"
    assert rows["employee_a"]["days"][0]["status"] == "present"
    assert rows["manager_a"]["days"] == []  # no schedule: nothing to report
    # A director sees both daycares
    everyone = client.get(f"/attendance?startDate={DAY}&endDate={DAY}", headers=login("director")).json()
    assert {row["person"]["username"] for row in everyone} == {"employee_a", "manager_a", "employee_b", "manager_b"}


def test_attendance_period_validations(client, login):
    headers = login("manager_a")
    assert client.get("/attendance?startDate=2026-02-01&endDate=2026-01-01", headers=headers).status_code == 400
    assert client.get("/attendance?startDate=2024-01-01&endDate=2026-01-01", headers=headers).status_code == 400
    assert client.get("/attendance?startDate=not-a-date", headers=headers).status_code == 400


# ── Manager fixes ────────────────────────────────────────────────────


def test_manager_fixes_a_record_directly(client, login):
    employee, manager = login("employee_a"), login("manager_a")
    record = clock_in(client, employee, time="07:30:00").json()["record"]
    fixed = client.put(f"/time-records/{record['id']}", headers=manager, json={"clockInAt": f"{DAY}T07:00:00", "clockOutAt": f"{DAY}T15:00:00"})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["clockInAt"] == f"{DAY}T13:00:00.000Z"
    assert fixed.json()["clockOutAt"] == f"{DAY}T21:00:00.000Z"
    # "clockOutAt": null removes the clock-out
    cleared = client.put(f"/time-records/{record['id']}", headers=manager, json={"clockOutAt": None})
    assert cleared.json()["clockOutAt"] is None
    # Another daycare's manager cannot
    assert client.put(f"/time-records/{record['id']}", headers=login("manager_b"), json={"clockOutAt": None}).status_code == 404
