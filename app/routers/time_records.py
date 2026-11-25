"""/time-records: clock-ins and clock-outs. Each row is an entry; the exit is filled in on the same row."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.constants import MAX_CLIENT_TIMESTAMP_AGE_HOURS
from app.dependencies import CurrentUser, DbSession, get_current_user
from app.errors import ApiError
from app.models import Daycare, User
from app.schemas import BatchIn, BatchOut, ClockInIn, ClockInOut, ClockOutIn, ClockStatusOut, TimeRecordOut
from app.services import records as record_service
from app.services.schedules import shifts_of_user_on
from app.timeutils import read_timestamp, today

router = APIRouter(prefix="/time-records", tags=["Time records"], dependencies=[Depends(get_current_user)])


def _require_room_and_shift_together(room_id: UUID | None, shift_id: UUID | None) -> None:
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


@router.post("/clock-in", response_model=ClockInOut, status_code=201)
def clock_in(body: ClockInIn, response: Response, user: CurrentUser, db: DbSession):
    """The person clocks in for themselves. Outside the zone it is saved anyway, for the manager to review.

    Sending the same uuid again (the phone lost the connection) returns the record already saved, with 200.
    """
    _require_room_and_shift_together(body.room_id, body.shift_id)
    when = read_timestamp(body.occurred_at, MAX_CLIENT_TIMESTAMP_AGE_HOURS)
    result = record_service.clock_in(
        db,
        user,
        when,
        recorded_by_id=user.id,
        source="app",
        record_uuid=body.uuid,
        latitude=body.latitude,
        longitude=body.longitude,
        # body.within_zone is deliberately NOT passed: the server decides from the coordinates
        room_id=body.room_id,
        shift_id=body.shift_id,
    )
    if result.error:
        raise ApiError(result.status, result.error)
    response.status_code = result.status
    return {"record": result.record, "attendance": result.attendance, "repeated": result.repeated}


@router.post("/clock-out", response_model=TimeRecordOut)
def clock_out(body: ClockOutIn, user: CurrentUser, db: DbSession):
    return record_service.clock_out(db, user, read_timestamp(body.occurred_at, MAX_CLIENT_TIMESTAMP_AGE_HOURS))


@router.post("/batch", response_model=BatchOut, status_code=201)
def clock_in_batch(body: BatchIn, user: CurrentUser, db: DbSession):
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
