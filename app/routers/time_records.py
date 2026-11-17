"""/time-records: clock-ins and clock-outs. Each row is an entry; the exit is filled in on the same row."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access import can_access_daycare, daycare_scope, require_found
from app.database import set_audit_user
from app.dependencies import CurrentUser, DbSession, EmployeeOrManager, ManagerOnly, get_current_user
from app.errors import ApiError
from app.models import Daycare, TimeRecord, User
from app.schemas import BatchIn, BatchOut, ClockInIn, ClockInOut, ClockOutIn, ClockStatusOut, RecordFixIn, TimeRecordOut
from app.services import records as record_service
from app.services.records import record_options
from app.services.schedules import shifts_of_user_on
from app.timeutils import day_end, day_start, now_utc, read_period, read_timestamp, today

router = APIRouter(prefix="/time-records", tags=["Time records"], dependencies=[Depends(get_current_user)])


def _require_room_and_shift_together(room_id: int | None, shift_id: int | None) -> None:
    if (room_id is None) != (shift_id is None):
        raise ApiError(400, "Send both roomId and shiftId, or neither")


@router.get("/status", response_model=ClockStatusOut)
def clock_status(user: CurrentUser, db: DbSession):
    """For the "clock in" screen: am I inside, what is my shift today, and where is the daycare."""
    open_one = record_service.open_record(db, user.id)
    return {
        "inside": open_one is not None,
        "open_record": open_one,
        "today_shifts": shifts_of_user_on(db, user.id, today()),
        "location": db.get(Daycare, user.daycare_id).location,
    }


@router.get("", response_model=list[TimeRecordOut])
def list_records(
    user: CurrentUser,
    db: DbSession,
    start_date: date | None = Query(None, alias="startDate", description="Default: Monday of this week"),
    end_date: date | None = Query(None, alias="endDate", description="Default: today"),
    user_id: int | None = Query(None, alias="userId"),
    within_zone: bool | None = Query(None, alias="withinZone"),
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    """Employees see their own records, managers their daycare's, directors all (or one with daycareId)."""
    start, end = read_period(start_date, end_date)
    stmt = (
        select(TimeRecord)
        .where(TimeRecord.clock_in_at >= day_start(start), TimeRecord.clock_in_at <= day_end(end))
        .options(*record_options())
        .order_by(TimeRecord.clock_in_at.desc())
    )
    if user.role_code == "employee":
        stmt = stmt.where(TimeRecord.user_id == user.id)
    else:
        scope = daycare_scope(user, daycare_id)
        if scope is not None:
            stmt = stmt.where(TimeRecord.user_id.in_(select(User.id).where(User.daycare_id == scope)))
        if user_id is not None:
            stmt = stmt.where(TimeRecord.user_id == user_id)
    if within_zone is not None:
        stmt = stmt.where(TimeRecord.within_zone.is_(within_zone))
    return db.scalars(stmt).all()


@router.post("/clock-in", response_model=ClockInOut, status_code=201)
def clock_in(body: ClockInIn, response: Response, user: EmployeeOrManager, db: DbSession):
    """The person clocks in for themselves. Outside the zone it is saved anyway, for the manager to review.

    Sending the same uuid again (the phone lost the connection) returns the record already saved, with 200.
    """
    _require_room_and_shift_together(body.room_id, body.shift_id)
    when = read_timestamp(body.occurred_at)
    result = record_service.clock_in(
        db,
        user,
        when,
        recorded_by_id=user.id,
        source="app",
        record_uuid=body.uuid,
        latitude=body.latitude,
        longitude=body.longitude,
        within_zone=body.within_zone,
        room_id=body.room_id,
        shift_id=body.shift_id,
    )
    if result.error:
        raise ApiError(result.status, result.error)
    response.status_code = result.status
    return {"record": result.record, "attendance": result.attendance, "repeated": result.repeated}


@router.post("/clock-out", response_model=TimeRecordOut)
def clock_out(body: ClockOutIn, user: EmployeeOrManager, db: DbSession):
    return record_service.clock_out(db, user, read_timestamp(body.occurred_at))


@router.post("/batch", response_model=BatchOut, status_code=201)
def clock_in_batch(body: BatchIn, user: ManagerOnly, db: DbSession):
    """The manager clocks in several people at once. The ones that cannot be recorded come back in "skipped"."""
    _require_room_and_shift_together(body.room_id, body.shift_id)
    when = read_timestamp(body.occurred_at)
    people = {
        person.id: person
        for person in db.scalars(
            select(User).where(
                User.id.in_(body.user_ids), User.is_active.is_(True), User.daycare_id == user.daycare_id
            )
        )
    }
    recorded, skipped = [], []
    for person_id in body.user_ids:
        person = people.get(person_id)
        if person is None:
            skipped.append({"user_id": person_id, "reason": "Not active staff of your daycare"})
            continue
        try:
            result = record_service.clock_in(
                db,
                person,
                when,
                recorded_by_id=user.id,
                source="manager",
                within_zone=True,
                room_id=body.room_id,
                shift_id=body.shift_id,
            )
        except IntegrityError:
            db.rollback()
            skipped.append({"user_id": person_id, "reason": "It could not be recorded"})
            continue
        if result.error:
            skipped.append({"user_id": person_id, "reason": result.error})
        else:
            recorded.append(result.record)
    return {"recorded": recorded, "skipped": skipped}


@router.put("/{record_id}", response_model=TimeRecordOut)
def fix_record(record_id: int, body: RecordFixIn, user: ManagerOnly, db: DbSession):
    """The manager corrects a record directly. The before/after is kept by the audit triggers."""
    record = db.scalars(select(TimeRecord).where(TimeRecord.id == record_id).options(*record_options())).first()
    record = require_found(record)
    if not can_access_daycare(user, record.user.daycare_id):
        raise ApiError(404, "Not found")

    clock_out_sent = "clock_out_at" in body.model_fields_set
    proposed = record_service.propose_times(
        record,
        read_timestamp(body.clock_in_at) if body.clock_in_at is not None else None,
        read_timestamp(body.clock_out_at) if body.clock_out_at is not None else None,
        clock_out_sent,
    )
    set_audit_user(db, user.id)
    record.clock_in_at = proposed.proposed_clock_in
    record.clock_out_at = proposed.proposed_clock_out
    db.commit()
    return record
