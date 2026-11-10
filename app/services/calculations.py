"""Attendance and coverage: puts together schedules, attendance rows and clock-ins, day by day.

Statuses of a day:
  present | late | absent | incident   what is stored in the attendance table
  no_record         had a shift and nobody recorded anything
  pending           today, has a shift, has not arrived yet
  day_off           no shift
  outside_schedule  clocked in without a shift
  scheduled         a future day with a shift
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.constants import ATTENDANCE_FROM_DB, MOVEMENT_TO_DB, ROLE_TO_DB
from app.models import Attendance, Daycare, Movement, Role, Schedule, Shift, TimeRecord, User
from app.services.schedules import schedule_load_options, shifts_on
from app.timeutils import (
    day_end,
    day_start,
    date_range,
    hhmm,
    local_date,
    local_hhmm,
    local_minutes,
    minutes_of,
    now_utc,
    to_local,
    today,
)

HIRE = MOVEMENT_TO_DB["hire"]
TERMINATION = MOVEMENT_TO_DB["termination"]


@dataclass
class PeriodData:
    people: list[User]
    attendance: dict[tuple[int, date], Attendance]
    records: dict[tuple[int, date], list[TimeRecord]]


def load_data(db: Session, person_filters: list, start: date, end: date) -> PeriodData:
    """People, schedules, attendance and clock-ins of a period, in a few queries.

    The people are everyone who is not a director and who is active (or was terminated
    during or after the period).
    """
    people = db.scalars(
        select(User)
        .join(User.role)
        .where(
            Role.name != ROLE_TO_DB["director"],
            or_(
                User.is_active.is_(True),
                User.movements.any(and_(Movement.type == TERMINATION, Movement.date >= start)),
            ),
            *person_filters,
        )
        .options(
            selectinload(User.role),
            selectinload(User.position),
            selectinload(User.daycare),
            selectinload(User.schedules.and_(Schedule.valid_from <= end, Schedule.valid_until >= start)).options(
                schedule_load_options()
            ),
            selectinload(User.movements.and_(Movement.type.in_([HIRE, TERMINATION]))),
        )
        .order_by(User.name)
    ).all()

    ids = [person.id for person in people]
    attendance_rows = db.scalars(
        select(Attendance)
        .where(Attendance.user_id.in_(ids), Attendance.date >= start, Attendance.date <= end)
        .options(selectinload(Attendance.absence_reason))
    ).all()
    record_rows = db.scalars(
        select(TimeRecord)
        .where(TimeRecord.user_id.in_(ids), TimeRecord.clock_in_at >= day_start(start), TimeRecord.clock_in_at <= day_end(end))
        .order_by(TimeRecord.clock_in_at)
    ).all()

    records: dict[tuple[int, date], list[TimeRecord]] = defaultdict(list)
    for record in record_rows:
        records[(record.user_id, local_date(record.clock_in_at))].append(record)
    return PeriodData(
        people=list(people),
        attendance={(row.user_id, row.date): row for row in attendance_rows},
        records=records,
    )


def was_active(person: User, day: date) -> bool:
    """Was the person already working that day, and not yet terminated? (from the movement history)"""
    hire = next((m for m in person.movements if m.type == HIRE), None)
    termination = next((m for m in reversed(person.movements) if m.type == TERMINATION), None)
    if hire and hire.date > day:
        return False
    if termination and not person.is_active and termination.date <= day:
        return False
    return True


def is_absence(status: str) -> bool:
    return status in ("absent", "no_record")


def compute_day(person: User, day: date, data: PeriodData) -> dict:
    """One day of one person."""
    shifts = shifts_on(person.schedules, day)
    attendance = data.attendance.get((person.id, day))
    records = data.records.get((person.id, day), [])
    first = records[0] if records else None
    last = records[-1] if records else None

    if attendance:
        status = ATTENDANCE_FROM_DB.get(attendance.status, attendance.status)
    elif day > today():
        status = "scheduled" if shifts else "day_off"
    elif first:
        status = "present" if shifts else "outside_schedule"
    elif not shifts:
        status = "day_off"
    else:
        status = "no_record" if day < today() else "pending"

    late_minutes = 0
    if first and shifts:
        shift_day = next((item for item in shifts if item.shift_id == first.shift_id), shifts[0])
        late_minutes = max(0, local_minutes(first.clock_in_at) - minutes_of(shift_day.shift.start_time))

    return {
        "date": day,
        "shifts": [
            {
                "shift_id": item.shift_id,
                "shift": item.shift.name,
                "start_time": hhmm(item.shift.start_time),
                "end_time": hhmm(item.shift.end_time),
                "room": {"id": item.room.id, "name": item.room.name},
            }
            for item in shifts
        ],
        "clock_in": local_hhmm(first.clock_in_at) if first else None,
        "clock_out": local_hhmm(last.clock_out_at) if last and last.clock_out_at else None,
        "within_zone": all(record.within_zone for record in records),
        "status": status,
        "reason": attendance.absence_reason.description if attendance and attendance.absence_reason else None,
        "reason_id": attendance.absence_reason_id if attendance else None,
        "attendance_id": attendance.id if attendance else None,
        "late_minutes": late_minutes if status == "late" else 0,
    }


def person_attendance(person: User, days: list[date], data: PeriodData) -> dict:
    """The person's days (newest first, without days off) and a summary."""
    rows = [compute_day(person, day, data) for day in days if was_active(person, day)]
    rows = [row for row in rows if row["status"] != "day_off"]
    rows.reverse()
    return {
        "person": person,
        "summary": {
            "worked_days": sum(1 for row in rows if row["clock_in"]),
            "lates": sum(1 for row in rows if row["status"] == "late"),
            "absences": sum(1 for row in rows if is_absence(row["status"])),
            "incidents": sum(1 for row in rows if row["status"] == "incident"),
        },
        "days": rows,
    }


def shift_started(day: date, shift: Shift) -> bool:
    """Has that shift started? Today, this afternoon's shift does not count as missing yet."""
    if day < today():
        return True
    if day > today():
        return False
    return minutes_of(to_local(now_utc()).time()) >= minutes_of(shift.start_time)


def compute_coverage(daycare: Daycare, shifts: list[Shift], day: date, data: PeriodData) -> dict:
    """A daycare on a day, by room and shift: people present against the minimum."""
    rooms = [
        {
            "room": {"id": room.id, "name": room.name},
            "minimum": room.min_staff,
            "shifts": [
                {"shift_id": shift.id, "shift": shift.name, "scheduled": 0, "present": 0} for shift in shifts
            ],
        }
        for room in daycare.rooms
    ]
    present = scheduled = pending = 0

    for person in data.people:
        if person.daycare_id != daycare.id or not was_active(person, day):
            continue
        info = compute_day(person, day, data)
        records = data.records.get((person.id, day), [])
        if records:
            present += 1
        if info["shifts"]:
            scheduled += 1
        if info["status"] == "pending":
            pending += 1
        for item in info["shifts"]:
            row = _find_row(rooms, item["room"]["id"], item["shift_id"])
            if row:
                row["scheduled"] += 1
        for record in records:
            row = _find_row(rooms, record.room_id, record.shift_id)
            if row:
                row["present"] += 1

    alerts = []
    shifts_by_id = {shift.id: shift for shift in shifts}
    for room in rooms:
        for row in room["shifts"]:
            row["started"] = shift_started(day, shifts_by_id[row["shift_id"]])
            row["uncovered"] = row["scheduled"] < room["minimum"]
            counted = row["present"] if row["started"] else row["scheduled"]
            row["missing"] = max(0, room["minimum"] - counted)
            row["below_minimum"] = row["missing"] > 0
            if row["below_minimum"]:
                alerts.append(f"Missing {row['missing']} in {room['room']['name']} ({row['shift']})")
    return {
        "daycare": {"id": daycare.id, "name": daycare.name},
        "date": day,
        "present": present,
        "scheduled": scheduled,
        "pending": pending,
        "complete": not alerts,
        "alerts": alerts,
        "rooms": rooms,
    }


def _find_row(rooms: list[dict], room_id: int, shift_id: int) -> dict | None:
    for room in rooms:
        if room["room"]["id"] == room_id:
            return next((row for row in room["shifts"] if row["shift_id"] == shift_id), None)
    return None


def load_daycares(db: Session, daycare_id: int | None = None) -> list[Daycare]:
    stmt = select(Daycare).options(selectinload(Daycare.rooms)).order_by(Daycare.id)
    if daycare_id is not None:
        stmt = stmt.where(Daycare.id == daycare_id)
    return list(db.scalars(stmt).all())


def ordered_shifts(db: Session) -> list[Shift]:
    return list(db.scalars(select(Shift).order_by(Shift.id)).all())


def build_statistics(db: Session, daycare_id: int | None, start: date, end: date) -> dict:
    """Hires, terminations, absences, lates and understaffed days for a period."""
    daycares = load_daycares(db, daycare_id)
    shifts = ordered_shifts(db)
    filters = [User.daycare_id == daycare_id] if daycare_id is not None else []
    data = load_data(db, filters, start, min(end, today()))
    movements = db.scalars(select(Movement).where(Movement.date >= start, Movement.date <= end)).all()
    past_days = [day for day in date_range(start, end) if day <= today()]

    understaffed_dates: set[date] = set()  # days when at least one daycare was under its minimum
    by_daycare = []
    for daycare in daycares:
        scheduled_days = absences = lates = 0
        for person in (p for p in data.people if p.daycare_id == daycare.id):
            for day in past_days:
                if not was_active(person, day):
                    continue
                info = compute_day(person, day, data)
                scheduled_days += 1 if info["shifts"] else 0
                absences += 1 if is_absence(info["status"]) else 0
                lates += 1 if info["status"] == "late" else 0
        understaffed_days = 0
        for day in past_days:
            if not compute_coverage(daycare, shifts, day, data)["complete"]:
                understaffed_dates.add(day)
                understaffed_days += 1

        def count(kind: str, column: str) -> int:
            return sum(1 for m in movements if m.type == MOVEMENT_TO_DB[kind] and getattr(m, column) == daycare.id)

        by_daycare.append(
            {
                "daycare": {"id": daycare.id, "name": daycare.name},
                "hires": count("hire", "destination_daycare_id"),
                "terminations": count("termination", "origin_daycare_id"),
                "transfers_in": count("transfer", "destination_daycare_id"),
                "transfers_out": count("transfer", "origin_daycare_id"),
                "understaffed_days": understaffed_days,
                "absences": absences,
                "lates": lates,
                "scheduled_days": scheduled_days,
            }
        )

    def total(field: str) -> int:
        return sum(row[field] for row in by_daycare)

    scheduled = total("scheduled_days")
    return {
        "start_date": start,
        "end_date": end,
        "hires": total("hires"),
        "terminations": total("terminations"),
        "absences": total("absences"),
        "lates": total("lates"),
        "understaffed_days": len(understaffed_dates),
        # percent with one decimal; floor(x + 0.5) rounds halves up, like the Node version
        "absenteeism": math.floor(total("absences") / scheduled * 1000 + 0.5) / 10 if scheduled else 0,
        "by_daycare": by_daycare,
    }
