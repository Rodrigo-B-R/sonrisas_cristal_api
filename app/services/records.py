"""Clock-in, clock-out and corrections of time records."""

import math
import uuid as uuid_lib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.constants import ATTENDANCE_TO_DB, SOURCE_TO_DB
from app.database import set_audit_user
from app.errors import ApiError
from app.models import Attendance, Daycare, Location, Room, Shift, TimeRecord, User
from app.services.schedules import shifts_of_user_on
from app.timeutils import local_date, local_minutes, minutes_of, seconds


def record_options():
    return (joinedload(TimeRecord.room), joinedload(TimeRecord.shift), joinedload(TimeRecord.user))


def open_record(db: Session, user_id: int) -> TimeRecord | None:
    """The clock-in the person has not clocked out of yet."""
    return db.scalars(
        select(TimeRecord)
        .where(TimeRecord.user_id == user_id, TimeRecord.clock_out_at.is_(None))
        .order_by(TimeRecord.clock_in_at.desc())
        .options(*record_options())
    ).first()


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine formula."""
    radians = math.radians
    a = (
        math.sin(radians(lat2 - lat1) / 2) ** 2
        + math.cos(radians(lat1)) * math.cos(radians(lat2)) * math.sin(radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371000 * math.asin(math.sqrt(a))


def is_within_zone(location: Location, latitude: float | None, longitude: float | None, within_zone: bool | None) -> bool:
    """With latitude and longitude it is calculated; without them, what the client says (true by default)."""
    if latitude is not None and longitude is not None:
        return distance_meters(latitude, longitude, location.latitude, location.longitude) <= location.radius_meters
    return True if within_zone is None else within_zone


def pick_room_and_shift(
    db: Session, person: User, when: datetime, room_id: int | None, shift_id: int | None
) -> tuple[Room, Shift] | None:
    """The room and shift of a clock-in: the ones sent, or the person's shift closest to the arrival."""
    if room_id is not None and shift_id is not None:
        room, shift = db.get(Room, room_id), db.get(Shift, shift_id)
        if room is None or room.daycare_id != person.daycare_id or shift is None:
            return None
        return room, shift
    days = shifts_of_user_on(db, person.id, local_date(when))
    if not days:
        return None
    arrival = local_minutes(when)
    best = min(days, key=lambda item: abs(minutes_of(item.shift.start_time) - arrival))
    return best.room, best.shift


def mark_attendance(db: Session, person: User, when: datetime, shift: Shift, recorded_by_id: int) -> Attendance:
    """Attendance of the day when someone arrives. If there already was one, it is left alone."""
    day = local_date(when)
    existing = db.scalars(
        select(Attendance).where(
            Attendance.user_id == person.id, Attendance.daycare_id == person.daycare_id, Attendance.date == day
        )
    ).first()
    if existing:
        return existing
    minutes_late = local_minutes(when) - minutes_of(shift.start_time)
    status = ATTENDANCE_TO_DB["late" if minutes_late > settings.late_tolerance_minutes else "present"]
    attendance = Attendance(
        date=day,
        status=status,
        user_id=person.id,
        recorded_by_id=recorded_by_id,
        daycare_id=person.daycare_id,
    )
    db.add(attendance)
    db.flush()
    return attendance


@dataclass
class ClockInResult:
    status: int
    record: TimeRecord | None = None
    attendance: Attendance | None = None
    repeated: bool = False
    error: str | None = None


def clock_in(
    db: Session,
    person: User,
    when: datetime,
    recorded_by_id: int,
    source: str,
    *,
    record_uuid: uuid_lib.UUID | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    within_zone: bool | None = None,
    room_id: int | None = None,
    shift_id: int | None = None,
) -> ClockInResult:
    """Registers an entry and the day's attendance, in one transaction.

    Saving the same uuid twice (a phone that re-sends after losing the connection) returns the
    record that was already saved instead of creating another.
    """
    record_uuid = record_uuid or uuid_lib.uuid4()
    repeated = db.scalars(
        select(TimeRecord).where(TimeRecord.uuid == record_uuid).options(*record_options())
    ).first()
    if repeated:
        if repeated.user_id != person.id:
            return ClockInResult(409, error="That uuid was already used")
        return ClockInResult(200, record=repeated, repeated=True)
    if open_record(db, person.id):
        return ClockInResult(409, error="There is already an open entry: clock out first")

    destination = pick_room_and_shift(db, person, when, room_id, shift_id)
    if destination is None:
        return ClockInResult(400, error="There is no schedule for that day: send roomId and shiftId of the person's daycare")
    room, shift = destination
    location = db.get(Daycare, person.daycare_id).location

    set_audit_user(db, recorded_by_id)
    record = TimeRecord(
        uuid=record_uuid,
        clock_in_at=when,
        source=SOURCE_TO_DB[source],
        within_zone=is_within_zone(location, latitude, longitude, within_zone),
        user_id=person.id,
        recorded_by_id=recorded_by_id,
        location_id=location.id,
        room_id=room.id,
        shift_id=shift.id,
    )
    db.add(record)
    db.flush()
    attendance = mark_attendance(db, person, when, shift, recorded_by_id)
    db.commit()
    record.room, record.shift, record.user = room, shift, person
    return ClockInResult(201, record=record, attendance=attendance)


def clock_out(db: Session, user: User, when: datetime) -> TimeRecord:
    record = open_record(db, user.id)
    if record is None:
        raise ApiError(409, "There is no open entry")
    if seconds(when) < seconds(record.clock_in_at):
        raise ApiError(400, "The clock-out must be after the clock-in")
    # Same second as the clock-in: saved one second later (the database requires clock-out > clock-in)
    out = when
    if seconds(when) == seconds(record.clock_in_at):
        out = datetime.fromtimestamp(seconds(record.clock_in_at) + 1, record.clock_in_at.tzinfo)
    set_audit_user(db, user.id)
    record.clock_out_at = out
    db.commit()
    return record


@dataclass
class ProposedTimes:
    previous_clock_in: datetime
    previous_clock_out: datetime | None
    proposed_clock_in: datetime
    proposed_clock_out: datetime | None


def propose_times(record: TimeRecord, clock_in_at: datetime | None, clock_out_at: datetime | None, clock_out_sent: bool) -> ProposedTimes:
    """The before/after times of a correction.

    clock_in_at None means "leave it". For the clock-out, clock_out_sent tells "not sent"
    (leave it) from an explicit null (remove it).
    """
    if clock_in_at is None and not clock_out_sent:
        raise ApiError(400, "Send clockInAt or clockOutAt")
    new_in = clock_in_at or record.clock_in_at
    new_out = clock_out_at if clock_out_sent else record.clock_out_at
    if new_out is not None and seconds(new_out) <= seconds(new_in):
        raise ApiError(400, "The clock-out must be after the clock-in")
    return ProposedTimes(record.clock_in_at, record.clock_out_at, new_in, new_out)
