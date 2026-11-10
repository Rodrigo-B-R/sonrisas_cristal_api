"""/schedules: the weekly schedule of each person.

Changing a schedule does not delete the old one: it is closed (validUntil = the day before) and a
new one is created, so we always know what a person's schedule was on any past date.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.access import daycare_scope, require_found
from app.constants import NO_END, ROLE_TO_DB, WEEKDAY_TO_DB
from app.dependencies import CurrentUser, DbSession, ManagerOnly, ManagerOrDirector, get_current_user
from app.errors import ApiError
from app.models import Role, Room, Schedule, ScheduleDay, Shift, User
from app.schemas import PersonScheduleOut, ScheduleIn, ScheduleOut
from app.services.schedules import current_schedule, schedule_load_options, schedule_of_user
from app.timeutils import today

router = APIRouter(prefix="/schedules", tags=["Schedules"], dependencies=[Depends(get_current_user)])


def _people_with_schedule(db, filters: list, day: date) -> list[dict]:
    people = db.scalars(
        select(User)
        .join(User.role)
        .where(User.is_active.is_(True), Role.name != ROLE_TO_DB["director"], *filters)
        .options(
            selectinload(User.position),
            selectinload(User.schedules.and_(Schedule.valid_from <= day, Schedule.valid_until >= day)).options(
                schedule_load_options()
            ),
        )
        .order_by(User.name)
    ).all()
    return [{"person": person, "schedule": current_schedule(person.schedules, day)} for person in people]


@router.get("/me", response_model=ScheduleOut | None)
def my_schedule(
    user: CurrentUser,
    db: DbSession,
    day: date | None = Query(None, alias="date", description="Default: today"),
):
    """Your own schedule on a date (null if you have none)."""
    return schedule_of_user(db, user.id, day or today())


@router.get("", response_model=list[PersonScheduleOut])
def list_schedules(
    user: ManagerOrDirector,
    db: DbSession,
    day: date | None = Query(None, alias="date", description="Default: today"),
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    """The schedule of every active person in the daycare on a date."""
    scope = daycare_scope(user, daycare_id)
    filters = [User.daycare_id == scope] if scope is not None else []
    return _people_with_schedule(db, filters, day or today())


@router.get("/{user_id}", response_model=PersonScheduleOut)
def get_schedule(
    user_id: int,
    user: ManagerOrDirector,
    db: DbSession,
    day: date | None = Query(None, alias="date", description="Default: today"),
):
    scope = daycare_scope(user)
    filters = [User.id == user_id] + ([User.daycare_id == scope] if scope is not None else [])
    rows = _people_with_schedule(db, filters, day or today())
    if not rows:
        raise ApiError(404, "Not found")
    return rows[0]


@router.put("/{user_id}", response_model=ScheduleOut, status_code=201)
def replace_schedule(user_id: int, body: ScheduleIn, user: ManagerOnly, db: DbSession):
    """Creates a new schedule for the person, valid from validFrom (default today).

    "days" lists the days they work. A weekday that is not listed is a day off.
    """
    person = require_found(db.get(User, user_id))
    if person.daycare_id != user.daycare_id:
        raise ApiError(404, "Not found")

    valid_from = body.valid_from or today()
    shifts = {shift.id for shift in db.scalars(select(Shift)).all()}
    rooms = {room.id for room in db.scalars(select(Room).where(Room.daycare_id == user.daycare_id)).all()}
    seen = set()
    for item in body.days:
        if item.shift_id not in shifts:
            raise ApiError(400, f"shiftId {item.shift_id} does not exist (see GET /catalogs)")
        if item.room_id not in rooms:
            raise ApiError(400, f"roomId {item.room_id} is not from your daycare")
        key = (item.day, item.shift_id, item.room_id)
        if key in seen:
            raise ApiError(400, f"{item.day} is repeated")
        seen.add(key)

    # Close the schedules that started before and were still valid on validFrom
    for old in db.scalars(
        select(Schedule).where(
            Schedule.user_id == person.id,
            Schedule.valid_from < valid_from,
            Schedule.valid_until >= valid_from,
        )
    ):
        old.valid_until = valid_from - timedelta(days=1)
    # Those that start that same day or later are covered by the new one (it has a higher id)
    schedule = Schedule(
        user_id=person.id,
        valid_from=valid_from,
        valid_until=NO_END,
        days=[
            ScheduleDay(weekday=WEEKDAY_TO_DB[item.day], shift_id=item.shift_id, room_id=item.room_id)
            for item in body.days
        ],
    )
    db.add(schedule)
    db.commit()
    return db.scalars(
        select(Schedule).options(schedule_load_options()).where(Schedule.id == schedule.id)
    ).one()
