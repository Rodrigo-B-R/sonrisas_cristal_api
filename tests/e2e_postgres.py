"""End-to-end check against the REAL PostgreSQL (the schema, triggers and permissions of sonrisas_cristal_db).

It is not collected by pytest (the unit tests run on SQLite). Run it after the database is up and seeded:

    python -m scripts.seed
    python -m tests.e2e_postgres

DATABASE_URL should be api_user's, to prove everything works with least privilege (no DELETE,
auditoria read-only). It writes rows (clock-ins, attendance...) that the API cannot delete, so use a
development database.
"""

import sys
from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.security import limiter
from app.timeutils import today

# Always yesterday: a clock-in sent later cannot be more than 48 hours old (MAX_CLIENT_TIMESTAMP_AGE_HOURS),
# so "the last day Ana works in the seed" (Monday to Thursday) failed on Saturdays, Sundays and Mondays.
# Ana gets a schedule that covers yesterday before clocking in (see "Schedule for the test day").
DAY = str(today() - timedelta(days=1))
WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def main() -> int:
    from app.config import settings

    password = settings.seed_password
    limiter.enabled = False
    results: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        results.append((name, bool(condition), detail))
        print(("PASS  " if condition else "FAIL  ") + name + (f"   [{detail}]" if detail and not condition else ""))

    with TestClient(app, raise_server_exceptions=False) as client:

        def login(username: str) -> dict:
            response = client.post("/login", json={"username": username, "password": password})
            assert response.status_code == 200, f"login {username}: {response.status_code} {response.text}"
            return {"Authorization": f"Bearer {response.json()['token']}"}

        ana, marisol, director = login("ana.torres"), login("marisol.garcia"), login("direccion")
        ana_id = client.get("/profile", headers=ana).json()["id"]
        marisol_id = client.get("/profile", headers=marisol).json()["id"]
        lucia_id = next(p["id"] for p in client.get("/staff", headers=marisol).json() if p["username"] == "lucia.herrera")

        # ── Basic reads on real PostgreSQL types ────────────────────────
        catalogs = client.get("/catalogs", headers=ana).json()
        check("catalogs: roles in English", sorted(r["name"] for r in catalogs["roles"]) == ["director", "employee", "manager"])
        check("catalogs: shifts as HH:MM", [(s["startTime"], s["endTime"]) for s in catalogs["shifts"]] == [("07:00", "15:00"), ("12:00", "20:00")])
        daycares = client.get("/daycares", headers=ana).json()
        # by name, not by position: the list is sorted by name (ids are random UUIDs)
        cumbres = next(d for d in daycares if d["name"] == "Cumbres")
        other_daycare = next(d for d in daycares if d["name"] != "Cumbres")
        check("daycares: 5 with rooms and location", len(daycares) == 5 and all(len(d["rooms"]) == 4 and d["location"] for d in daycares))
        check("manager only sees her daycare", {p["daycare"]["name"] for p in client.get("/staff", headers=marisol).json()} == {"Cumbres"})
        check("staff: 9 people for the director", len(client.get("/staff", headers=director).json()) == 9)

        # ── Schedule for the test day ───────────────────────────────────
        # Morning shift every day from yesterday, so yesterday is a work day whatever weekday it was.
        # It also replaces the seed schedule: the newest one (creado_en) must win on that day.
        morning = next(s["id"] for s in catalogs["shifts"] if s["name"] == "matutino")
        maternal_a = next(r["id"] for r in cumbres["rooms"] if r["name"] == "Maternal A")
        week = [{"day": day, "shiftId": morning, "roomId": maternal_a} for day in WEEK]
        ana_schedule = client.put(f"/schedules/{ana_id}", headers=marisol, json={"validFrom": DAY, "days": week})
        check("schedule for the test day: 201", ana_schedule.status_code == 201, ana_schedule.text[:200])
        mine = client.get(f"/schedules/me?date={DAY}", headers=ana).json()
        check("the new schedule is the one in force", mine is not None and len(mine["days"]) == 7, str(mine)[:200])

        # ── Clock-in with the audit author ──────────────────────────────
        key = "5f1c3d2a-7b1e-4c55-9a77-0a1b2c3d4e5f"
        first = client.post(
            "/time-records/clock-in",
            headers=ana,
            json={"uuid": key, "occurredAt": f"{DAY}T07:20:00", "latitude": 25.7447, "longitude": -100.4036},
        )
        check("clock-in 201", first.status_code == 201, first.text[:200])
        if first.status_code != 201:
            # everything below uses this record: report what we have instead of crashing
            print(f"\n{sum(ok for _, ok, _ in results)}/{len(results)} checks passed (stopped: the clock-in failed)")
            return 1
        body = first.json()
        check("clock-in: late (20 min)", body["attendance"]["status"] == "late")
        check("clock-in: within zone by GPS", body["record"]["withinZone"] is True)
        check("clock-in: UTC timestamp", body["record"]["clockInAt"] == f"{DAY}T13:20:00.000Z", body["record"]["clockInAt"])
        again = client.post("/time-records/clock-in", headers=ana, json={"uuid": key, "occurredAt": f"{DAY}T07:20:00"})
        check("same uuid: 200 and repeated", again.status_code == 200 and again.json()["repeated"] is True)
        out = client.post("/time-records/clock-out", headers=ana, json={"occurredAt": f"{DAY}T15:00:00"})
        check("clock-out", out.status_code == 200 and out.json()["clockOutAt"] == f"{DAY}T21:00:00.000Z", out.text[:200])
        record_id = body["record"]["id"]

        # ── Manager fix ─────────────────────────────────────────────────
        direct = client.put(f"/time-records/{record_id}", headers=marisol, json={"clockOutAt": f"{DAY}T14:30:00"})
        check("manager fixes a record directly", direct.status_code == 200, direct.text[:200])

        # ── Attendance (CHECK constraint: absent needs a reason) ────────
        no_reason = client.post("/attendance", headers=marisol, json={"userId": lucia_id, "date": DAY, "status": "absent"})
        check("absent without a reason: 400", no_reason.status_code == 400)
        absent = client.post("/attendance", headers=marisol, json={"userId": lucia_id, "date": DAY, "status": "absent", "absenceReason": "enfermedad"})
        check("absence with a reason: 201", absent.status_code == 201, absent.text[:200])

        # ── The audit log has the right author for every change ─────────
        audit = client.get(f"/audit?startDate={DAY}&endDate={today()}", headers=director).json()
        by_table: dict[str, list] = {}
        for entry in audit:
            by_table.setdefault(entry["table"], []).append(entry)
        check("audit: the two tables are there", set(by_table) == {"registro_entradas", "asistencia"}, str(set(by_table)))
        check("audit: no change without an author", all(e["userId"] is not None for e in audit), str([e for e in audit if e["userId"] is None][:2]))

        def authors(table: str, action: str) -> set:
            return {e["userId"] for e in by_table.get(table, []) if e["action"] == action}

        check("audit: clock-in written by ana", ana_id in authors("registro_entradas", "INSERT"))
        check("audit: record updates written by ana and marisol", {ana_id, marisol_id} <= authors("registro_entradas", "UPDATE"))
        check("audit: absence written by marisol", marisol_id in authors("asistencia", "INSERT"))
        previous = next(e for e in by_table["registro_entradas"] if e["action"] == "UPDATE")
        check("audit: keeps previous and new data", previous["previousData"] and previous["newData"])
        check("audit: shows the author's name", all(e["user"]["name"] for e in audit))

        # ── Reports on real data ────────────────────────────────────────
        report = client.get(f"/attendance/me?startDate={DAY}&endDate={DAY}", headers=ana).json()
        # arrived 07:20 (20 min late); the manager fixed only the clock-out, to 14:30
        day = report["days"][0]
        check("attendance/me", (day["clockIn"], day["clockOut"], day["status"]) == ("07:20", "14:30", "late"), str(day))
        listing = client.get(f"/attendance?startDate={DAY}&endDate={DAY}", headers=marisol).json()
        lucia = next(row for row in listing if row["person"]["id"] == lucia_id)
        check("attendance report shows the absence with its reason", lucia["days"][0]["status"] == "absent" and lucia["days"][0]["reason"] == "enfermedad")
        coverage = client.get(f"/coverage?date={DAY}", headers=marisol).json()
        check("coverage", coverage["daycare"]["name"] == "Cumbres" and len(coverage["rooms"]) == 4)
        summary = client.get(f"/summary?date={DAY}", headers=director).json()
        check("summary: 5 daycares", summary["completeCount"] + summary["understaffedCount"] == 5)
        # /statistics allows at most 92 days; the seed hires are on 2025-01-12
        stats = client.get("/statistics?startDate=2025-01-01&endDate=2025-03-31", headers=director).json()
        check("statistics: hires from the seed", stats["hires"] >= 9 and len(stats["byDaycare"]) == 5)
        csv = client.get(f"/export/attendance?startDate={DAY}&endDate={DAY}", headers=marisol)
        check("csv export", csv.status_code == 200 and "Ana Torres" in csv.content.decode("utf-8-sig"))
        movements = client.get("/movements?startDate=2025-01-01&endDate=2025-12-31", headers=director).json()
        check("movements: hires from the seed", len(movements) >= 9 and all(m["type"] == "hire" for m in movements))

        # ── Notices, schedules, hire (INSERT ... with UUID ids) ─────
        inbox = client.get("/notices/inbox", headers=ana).json()
        check("notices: seed notice in the inbox", len(inbox) == 1 and inbox[0]["read"] is False)
        read = client.post(f"/notices/{inbox[0]['id']}/read", headers=ana)
        check("notices: confirm reading (leido/leido_en CHECK)", read.status_code == 200 and read.json()["read"] is True and read.json()["readAt"])
        general = client.post("/notices", headers=director, json={"subject": "Todos", "message": "Aviso general", "noticeType": "reminder"})
        check("notices: general notice from the director", general.status_code == 201 and general.json()["daycareId"] is None, general.text[:200])
        position = client.get("/catalogs", headers=ana).json()["positions"][0]["id"]
        hired = client.post("/staff", headers=marisol, json={"name": "Prueba E2E", "username": "prueba.e2e", "email": "e2e@sonrisascristal.mx", "phone": "81", "positionId": position})
        check("hire: user + movement in one transaction", hired.status_code == 201, hired.text[:200])
        duplicate = client.post("/staff", headers=marisol, json={"name": "Otra", "username": "prueba.e2e", "email": "otra@sonrisascristal.mx", "phone": "81", "positionId": position})
        check("duplicate username: 409 (UNIQUE constraint)", duplicate.status_code == 409, duplicate.text[:200])
        new_id = hired.json()["id"]
        schedule = client.put(f"/schedules/{new_id}", headers=marisol, json={"validFrom": str(today()), "days": [{"day": "monday", "shiftId": catalogs["shifts"][0]["id"], "roomId": cumbres["rooms"][0]["id"]}]})
        check("schedule replaced", schedule.status_code == 201, schedule.text[:200])

        # ── A01 on the real database: a token never goes stale ──────────
        new_login = client.post("/login", json={"username": "prueba.e2e", "password": hired.json()["temporaryPassword"]})
        check("new hire logs in with the temporary password", new_login.status_code == 200)
        new_headers = {"Authorization": f"Bearer {new_login.json()['token']}"}
        reason = client.get("/catalogs", headers=ana).json()["terminationReasons"][0]["id"]
        done = client.post(f"/staff/{new_id}/terminate", headers=marisol, json={"terminationReasonId": reason})
        check("terminate (movement CHECK constraints)", done.status_code == 200, done.text[:200])
        check("terminated person's token stops working at once", client.get("/profile", headers=new_headers).status_code == 401)
        transfer = client.post(f"/staff/{lucia_id}/transfer", headers=director, json={"daycareId": other_daycare["id"]})
        check("transfer (movement CHECK constraints)", transfer.status_code == 200, transfer.text[:200])
        check("transferred person leaves the old manager's view", client.get(f"/staff/{lucia_id}", headers=marisol).status_code == 404)

        # ── Metrics see the real pool ───────────────────────────────────
        metrics = client.get("/metrics", headers={"Authorization": f"Bearer {settings.metrics_token}"}) if settings.metrics_token else None
        if metrics is not None:
            check("metrics: db pool gauge", 'db_pool_connections{state="total"}' in metrics.text)

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
