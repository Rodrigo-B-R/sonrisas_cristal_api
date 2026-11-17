"""Test data: two daycares (A and B), a director, and in each daycare a manager and an employee."""

from datetime import date, time

from app.constants import NO_END, ROLE_TO_DB, WEEKDAY_TO_DB, WEEKDAYS
from app.models import (
    AbsenceReason,
    Daycare,
    Location,
    Movement,
    Position,
    Role,
    Room,
    Schedule,
    ScheduleDay,
    Shift,
    TerminationReason,
    User,
)
from app.security import hash_password


def build_world(db, password: str) -> dict:
    roles = {name: Role(name=db_name) for name, db_name in ROLE_TO_DB.items()}
    position = Position(name="Maestra titular")
    morning = Shift(name="matutino", start_time=time(7, 0), end_time=time(15, 0))
    evening = Shift(name="vespertino", start_time=time(12, 0), end_time=time(20, 0))
    db.add_all([*roles.values(), position, morning, evening])
    db.add_all([AbsenceReason(description="enfermedad"), AbsenceReason(description="permiso")])
    db.add(TerminationReason(name="Renuncia"))

    daycares = {}
    for key, name, lat in (("a", "Cumbres", 25.7447), ("b", "Apodaca", 25.7817)):
        daycares[key] = Daycare(name=name, location=Location(name=f"Daycare {name}", latitude=lat, longitude=-100.4, radius_meters=150))
        daycares[key].rooms = [Room(name="Lactantes", min_staff=1), Room(name="Maternal", min_staff=1)]
    db.add_all(daycares.values())
    db.flush()

    hashed = hash_password(password)
    people = {}
    for username, role, daycare in (
        ("director", "director", "a"),
        ("manager_a", "manager", "a"),
        ("employee_a", "employee", "a"),
        ("manager_b", "manager", "b"),
        ("employee_b", "employee", "b"),
    ):
        user = User(
            name=username.replace("_", " ").title(),
            username=username,
            email=f"{username}@example.com",
            phone="8110000000",
            password_hash=hashed,
            is_active=True,
            role=roles[role],
            position=position,
            daycare=daycares[daycare],
        )
        db.add(user)
        people[username] = user
    db.flush()

    for user in people.values():
        db.add(Movement(type="alta", date=date(2020, 1, 1), user_id=user.id, done_by_id=people["director"].id, destination_daycare_id=user.daycare_id))
    # The employees work every day, in the morning, in the first room of their daycare
    for key in ("a", "b"):
        employee = people[f"employee_{key}"]
        schedule = Schedule(user_id=employee.id, valid_from=date(2020, 1, 1), valid_until=NO_END)
        schedule.days = [
            ScheduleDay(weekday=WEEKDAY_TO_DB[day], shift_id=morning.id, room_id=daycares[key].rooms[0].id) for day in WEEKDAYS
        ]
        db.add(schedule)
    db.commit()

    return {
        "ids": {name: user.id for name, user in people.items()},
        "daycare_a": daycares["a"].id,
        "daycare_b": daycares["b"].id,
        "room_a": daycares["a"].rooms[0].id,
        "room_b": daycares["b"].rooms[0].id,
        "morning": morning.id,
        "evening": evening.id,
        "position": position.id,
    }
