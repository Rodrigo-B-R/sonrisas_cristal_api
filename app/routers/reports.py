"""Reports: GET /coverage, /summary, /statistics and /export/attendance."""

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Query, Response

from app.access import daycare_scope
from app.dependencies import DbSession, DirectorOnly, ManagerOrDirector, get_current_user
from app.errors import ApiError
from app.models import User
from app.schemas import CoverageOut, StatisticsOut, SummaryOut
from app.services.calculations import (
    build_statistics,
    compute_coverage,
    load_data,
    load_daycares,
    ordered_shifts,
    person_attendance,
)
from app.timeutils import date_range, first_of_month, read_period, today

router = APIRouter(tags=["Reports"], dependencies=[Depends(get_current_user)])


@router.get("/coverage", response_model=CoverageOut)
def coverage(
    user: ManagerOrDirector,
    db: DbSession,
    day: date | None = Query(None, alias="date", description="Default: today"),
    daycare_id: int | None = Query(None, alias="daycareId", description="Required for directors"),
):
    """Staff present against the minimum of each room and shift, in one daycare on one day."""
    day = day or today()
    scope = daycare_scope(user, daycare_id)
    if scope is None:
        raise ApiError(400, "Missing daycareId")
    daycares = load_daycares(db, scope)
    if not daycares:
        raise ApiError(404, "Daycare not found")
    data = load_data(db, [User.daycare_id == scope], day, day)
    return compute_coverage(daycares[0], ordered_shifts(db), day, data)


@router.get("/summary", response_model=SummaryOut)
def summary(
    user: DirectorOnly,
    db: DbSession,
    day: date | None = Query(None, alias="date", description="Default: today"),
):
    """Every daycare on one day: which ones are complete and which are short of staff."""
    day = day or today()
    shifts = ordered_shifts(db)
    data = load_data(db, [], day, day)
    rows = []
    for daycare in load_daycares(db):
        result = compute_coverage(daycare, shifts, day, data)
        rows.append(
            {
                **result["daycare"],
                "complete": result["complete"],
                "alerts": result["alerts"],
                "present": result["present"],
                "scheduled": result["scheduled"],
            }
        )
    return {
        "date": day,
        "complete_count": sum(1 for row in rows if row["complete"]),
        "understaffed_count": sum(1 for row in rows if not row["complete"]),
        "daycares": rows,
    }


@router.get("/statistics", response_model=StatisticsOut)
def statistics(
    user: ManagerOrDirector,
    db: DbSession,
    start_date: date | None = Query(None, alias="startDate", description="Default: the first day of this month"),
    end_date: date | None = Query(None, alias="endDate", description="Default: today"),
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    start, end = read_period(start_date, end_date, default_start=first_of_month(today()), max_days=400)
    return build_statistics(db, daycare_scope(user, daycare_id), start, end)


def _safe_cell(value) -> str:
    """Stops spreadsheet formula injection: a text that starts with = + - @ would run as a formula in Excel."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/export/attendance", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
def export_attendance(
    user: ManagerOrDirector,
    db: DbSession,
    start_date: date | None = Query(None, alias="startDate", description="Default: the first day of this month"),
    end_date: date | None = Query(None, alias="endDate", description="Default: today"),
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    """Attendance of the period as a CSV file."""
    start, end = read_period(start_date, end_date, default_start=first_of_month(today()), max_days=400)
    end = min(end, today())
    start = min(start, end)
    scope = daycare_scope(user, daycare_id)
    data = load_data(db, [User.daycare_id == scope] if scope is not None else [], start, end)
    days = date_range(start, end)

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(
        ["daycare", "name", "username", "position", "date", "shift", "room", "scheduled_time",
         "clock_in", "clock_out", "status", "reason", "late_minutes", "within_zone"]
    )
    for person in data.people:
        for day in reversed(person_attendance(person, days, data)["days"]):  # oldest first
            first = day["shifts"][0] if day["shifts"] else None
            writer.writerow(
                [
                    _safe_cell(value)
                    for value in (
                        person.daycare.name,
                        person.name,
                        person.username,
                        person.position.name,
                        day["date"],
                        " + ".join(item["shift"] for item in day["shifts"]),
                        " + ".join(item["room"]["name"] for item in day["shifts"]),
                        f"{first['start_time']}-{first['end_time']}" if first else "",
                        day["clock_in"],
                        day["clock_out"],
                        day["status"],
                        day["reason"],
                        day["late_minutes"],
                        "yes" if day["within_zone"] else "no",
                    )
                ]
            )
    # The BOM makes Excel read the accents correctly
    return Response(
        content="﻿" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="attendance_{start}_{end}.csv"'},
    )
