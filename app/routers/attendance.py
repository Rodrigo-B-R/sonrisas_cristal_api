"""/attendance: present and late are saved by themselves when someone clocks in;
absent and incident are set by the manager.

The reports put together schedule + attendance + clock-ins of each day (see services/calculations.py).
"""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from app.access import can_access_daycare, daycare_scope, require_found
from app.constants import ATTENDANCE_FROM_DB, ATTENDANCE_TO_DB
from app.database import set_audit_user
from app.dependencies import CurrentUser, DbSession, ManagerOnly, ManagerOrDirector, get_current_user
from app.errors import ApiError
from app.models import AbsenceReason, Attendance, User
from app.schemas import (
    AttendanceIn,
    AttendanceOut,
    AttendanceUpdateIn,
    PersonAttendanceOut,
    SinglePersonAttendanceOut,
)
from app.services.calculations import load_data, person_attendance, was_active
from app.timeutils import date_range, read_period, today

router = APIRouter(prefix="/attendance", tags=["Attendance"], dependencies=[Depends(get_current_user)])


def _resolve_reason(db, status: str, reason_id: int | None, description: str | None) -> int | None:
    """The reason comes from the absence-reasons catalog: send reasonId or the description.

    Absent and incident need one. Returns the reason id (or None).
    """
    found = None
    if reason_id is not None:
        found = db.get(AbsenceReason, reason_id)
    elif description is not None:
        found = db.scalars(select(AbsenceReason).where(AbsenceReason.description == description)).first()
    sent = reason_id is not None or description is not None
    if (sent and found is None) or (status in ("absent", "incident") and found is None):
        options = [{"id": r.id, "description": r.description} for r in db.scalars(select(AbsenceReason).order_by(AbsenceReason.id))]
        message = "Invalid reason" if sent else "Absent and incident need a reason (absenceReasonId or absenceReason)"
        raise ApiError(400, message, options=options)
    return found.id if found else None


def _period(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    start, end = read_period(start_date, end_date, max_days=400)
    end = min(end, today())  # the future has no attendance yet
    return min(start, end), end


@router.get("", response_model=list[PersonAttendanceOut])
def list_attendance(
    user: ManagerOrDirector,
    db: DbSession,
    start_date: date | None = Query(None, alias="startDate", description="Default: Monday of this week"),
    end_date: date | None = Query(None, alias="endDate", description="Default: today"),
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    """Everyone in the daycare: summary and days of each person. Directors are not included, nor is anyone who had not been hired yet or was already terminated in the whole period."""
    start, end = _period(start_date, end_date)
    scope = daycare_scope(user, daycare_id)
    data = load_data(db, [User.daycare_id == scope] if scope is not None else [], start, end)
    days = date_range(start, end)
    return [person_attendance(p, days, data) for p in data.people if any(was_active(p, d) for d in days)]


def _single(db, filters: list, start: date, end: date) -> dict:
    data = load_data(db, filters, start, end)
    if not data.people:
        raise ApiError(404, "Not found")
    return {"start_date": start, "end_date": end, **person_attendance(data.people[0], date_range(start, end), data)}


@router.get("/me", response_model=SinglePersonAttendanceOut)
def my_attendance(
    user: CurrentUser,
    db: DbSession,
    start_date: date | None = Query(None, alias="startDate"),
    end_date: date | None = Query(None, alias="endDate"),
):
    """Your own attendance ("My attendance" screen)."""
    start, end = _period(start_date, end_date)
    return _single(db, [User.id == user.id], start, end)


@router.get("/{user_id}", response_model=SinglePersonAttendanceOut)
def person_attendance_report(
    user_id: int,
    user: ManagerOrDirector,
    db: DbSession,
    start_date: date | None = Query(None, alias="startDate"),
    end_date: date | None = Query(None, alias="endDate"),
):
    start, end = _period(start_date, end_date)
    scope = daycare_scope(user)
    filters = [User.id == user_id] + ([User.daycare_id == scope] if scope is not None else [])
    return _single(db, filters, start, end)


@router.post("", response_model=AttendanceOut, status_code=201)
def set_attendance(body: AttendanceIn, response: Response, user: ManagerOnly, db: DbSession):
    """The manager marks an absence or incident, or fixes the status of a day. 201 if new, 200 if it corrected one."""
    reason_id = _resolve_reason(db, body.status, body.absence_reason_id, body.absence_reason)
    person = db.get(User, body.user_id)
    if person is None or not can_access_daycare(user, person.daycare_id):
        raise ApiError(404, "Person not found")

    existing = db.scalars(
        select(Attendance).where(
            Attendance.user_id == person.id,
            Attendance.daycare_id == person.daycare_id,
            Attendance.date == body.date,
        )
    ).first()
    set_audit_user(db, user.id)
    status = ATTENDANCE_TO_DB[body.status]
    if existing:
        existing.status, existing.absence_reason_id, existing.recorded_by_id = status, reason_id, user.id
        attendance = existing
        response.status_code = 200
    else:
        attendance = Attendance(
            date=body.date,
            status=status,
            absence_reason_id=reason_id,
            user_id=person.id,
            recorded_by_id=user.id,
            daycare_id=person.daycare_id,
        )
        db.add(attendance)
    db.commit()
    db.refresh(attendance)
    return attendance


@router.put("/{attendance_id}", response_model=AttendanceOut)
def fix_attendance(attendance_id: int, body: AttendanceUpdateIn, user: ManagerOnly, db: DbSession):
    attendance = require_found(db.get(Attendance, attendance_id))
    if not can_access_daycare(user, attendance.daycare_id):
        raise ApiError(404, "Not found")
    status = body.status or ATTENDANCE_FROM_DB[attendance.status]
    reason_id = _resolve_reason(db, status, body.absence_reason_id, body.absence_reason)
    set_audit_user(db, user.id)
    attendance.status = ATTENDANCE_TO_DB[status]
    attendance.absence_reason_id = reason_id
    attendance.recorded_by_id = user.id
    db.commit()
    db.refresh(attendance)
    return attendance
