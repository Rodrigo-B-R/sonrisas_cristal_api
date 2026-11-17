"""Which schedule is valid on a day, and which shifts does a person have on it."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.constants import WEEKDAY_TO_DB
from app.models import Schedule, ScheduleDay
from app.timeutils import weekday_name


def schedule_load_options():
    """Load a schedule with its days, shifts and rooms in a few queries."""
    return selectinload(Schedule.days).options(selectinload(ScheduleDay.shift), selectinload(ScheduleDay.room))


def current_schedule(schedules: list[Schedule], day: date) -> Schedule | None:
    """The schedule that covers the day. If two do, the newest one (highest id) wins."""
    valid = [item for item in schedules if item.valid_from <= day <= item.valid_until]
    return max(valid, key=lambda item: item.id, default=None)


def shifts_on(schedules: list[Schedule], day: date) -> list[ScheduleDay]:
    """The shifts a person has that day. Empty means a day off."""
    schedule = current_schedule(schedules, day)
    if schedule is None:
        return []
    weekday = WEEKDAY_TO_DB[weekday_name(day)]
    return [item for item in schedule.days if item.weekday == weekday]


def schedule_of_user(db: Session, user_id: int, day: date) -> Schedule | None:
    schedules = db.scalars(
        select(Schedule)
        .options(schedule_load_options())
        .where(Schedule.user_id == user_id, Schedule.valid_from <= day, Schedule.valid_until >= day)
    ).all()
    return current_schedule(list(schedules), day)


def shifts_of_user_on(db: Session, user_id: int, day: date) -> list[ScheduleDay]:
    schedule = schedule_of_user(db, user_id, day)
    if schedule is None:
        return []
    weekday = WEEKDAY_TO_DB[weekday_name(day)]
    return [item for item in schedule.days if item.weekday == weekday]
