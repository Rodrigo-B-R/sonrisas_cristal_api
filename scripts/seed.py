"""python -m scripts.seed

Test data. Safe to run several times: it does not duplicate anything and it sets every test
account's password back to SEED_PASSWORD. NEVER run it against production.

The catalog values (roles, positions, rooms...) and the people are sample business data in
Spanish, like the daycares themselves. The roles are stored the way the database expects
them (empleada, responsable, direccion).
"""

from datetime import date, time

from sqlalchemy import func, select

from app.config import settings
from app.constants import NO_END, ROLE_TO_DB, WEEKDAY_TO_DB, WEEKDAYS
from app.database import SessionLocal
from app.models import (
    AbsenceReason,
    Daycare,
    Location,
    Movement,
    Notice,
    NoticeRecipient,
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

HIRE_DATE = date(2025, 1, 12)

POSITIONS = ["Dirección", "Responsable de estancia", "Maestra titular", "Asistente", "Auxiliar", "Cocina", "Intendencia"]
TERMINATION_REASONS = ["Renuncia", "Fin de contrato", "Abandono de trabajo", "Otro"]
ABSENCE_REASONS = ["enfermedad", "permiso", "personal", "transporte", "otro"]
SHIFTS = [("matutino", time(7, 0), time(15, 0)), ("vespertino", time(12, 0), time(20, 0))]

# (name, latitude, longitude): the radius is 150 m
DAYCARES = [
    ("Cumbres", 25.7447, -100.4036),
    ("San Nicolás", 25.7417, -100.302),
    ("Apodaca", 25.7817, -100.1886),
    ("Guadalupe", 25.6775, -100.2597),
    ("Escobedo", 25.7953, -100.317),
]

# (name, minimum staff): the "Rooms and minimums" screen
ROOMS = [("Lactantes", 2), ("Maternal A", 3), ("Maternal B", 3), ("Preescolar", 4)]

# A week from Monday to Sunday: M = morning, V = evening, · = day off
EMPLOYEES = [
    ("ana.torres", "Ana Torres", "Maestra titular", "Maternal A", "MMMM···"),
    ("lucia.herrera", "Lucía Herrera", "Maestra titular", "Lactantes", "M·MMMM·"),
    ("carmen.ruiz", "Carmen Ruiz", "Asistente", "Maternal B", "VVVV·V·"),
    ("sofia.diaz", "Sofía Díaz", "Maestra titular", "Preescolar", "MM·MM··"),
    ("paola.reyes", "Paola Reyes", "Auxiliar", "Maternal A", "·MMMM·V"),
    ("rosa.medina", "Rosa Medina", "Cocina", "Lactantes", "MMMMM··"),
    ("maria.lopez", "María López", "Asistente", "Maternal A", "MMM·M··"),
]


def get_or_create(db, model, where: dict, **extra):
    """Finds a row by the 'where' columns; creates it if it does not exist (catalogs have no unique name)."""
    found = db.scalars(select(model).filter_by(**where)).first()
    if found:
        return found
    created = model(**where, **extra)
    db.add(created)
    db.flush()
    return created


def main() -> None:
    password_hash = hash_password(settings.seed_password)
    with SessionLocal() as db:
        roles = {name: get_or_create(db, Role, {"name": db_name}) for name, db_name in ROLE_TO_DB.items()}
        positions = {name: get_or_create(db, Position, {"name": name}) for name in POSITIONS}
        for description in ABSENCE_REASONS:
            get_or_create(db, AbsenceReason, {"description": description})
        for name in TERMINATION_REASONS:
            get_or_create(db, TerminationReason, {"name": name})
        shifts = {
            name: get_or_create(db, Shift, {"name": name}, start_time=start, end_time=end) for name, start, end in SHIFTS
        }

        daycares = {}
        for name, latitude, longitude in DAYCARES:
            daycare = db.scalars(select(Daycare).where(Daycare.name == name)).first()
            if daycare is None:
                daycare = Daycare(
                    name=name,
                    location=Location(name=f"Estancia {name}", latitude=latitude, longitude=longitude, radius_meters=150),
                )
                db.add(daycare)
                db.flush()
            daycares[name] = daycare
            for room_name, minimum in ROOMS:
                get_or_create(db, Room, {"name": room_name, "daycare_id": daycare.id}, min_staff=minimum)
        cumbres = daycares["Cumbres"]
        rooms = {room.name: room for room in db.scalars(select(Room).where(Room.daycare_id == cumbres.id))}

        director: User | None = None

        def create_user(username: str, name: str, role: str, position: str, number: int) -> User:
            data = dict(
                name=name,
                email=f"{username}@sonrisascristal.mx",
                phone=f"81 1000 {number:04d}",
                role_id=roles[role].id,
                position_id=positions[position].id,
                daycare_id=cumbres.id,
            )
            user = db.scalars(select(User).where(User.username == username)).first()
            if user is None:
                user = User(username=username, password_hash=password_hash, is_active=True, **data)
                db.add(user)
            else:  # the same as the Node seed: it also resets the password and reactivates the account
                for key, value in data.items():
                    setattr(user, key, value)
                user.password_hash, user.is_active = password_hash, True
            db.flush()
            has_hire = db.scalars(select(Movement).where(Movement.user_id == user.id, Movement.type == "alta")).first()
            if not has_hire:
                db.add(
                    Movement(
                        type="alta",
                        date=HIRE_DATE,
                        user_id=user.id,
                        done_by_id=(director or user).id,
                        destination_daycare_id=cumbres.id,
                    )
                )
            return user

        director = create_user("direccion", "Dirección General", "director", "Dirección", 1)
        manager = create_user("marisol.garcia", "Marisol García", "manager", "Responsable de estancia", 2)

        employees = []
        for number, (username, name, position, room, week) in enumerate(EMPLOYEES, start=3):
            employee = create_user(username, name, "employee", position, number)
            employees.append(employee)
            if db.scalars(select(Schedule).where(Schedule.user_id == employee.id)).first():
                continue
            days = [
                ScheduleDay(
                    weekday=WEEKDAY_TO_DB[WEEKDAYS[index]],
                    shift_id=shifts["matutino" if letter == "M" else "vespertino"].id,
                    room_id=rooms[room].id,
                )
                for index, letter in enumerate(week)
                if letter != "·"
            ]
            db.add(Schedule(user_id=employee.id, valid_from=HIRE_DATE, valid_until=NO_END, days=days))

        if db.scalar(select(func.count()).select_from(Notice)) == 0:
            db.add(
                Notice(
                    subject="Bienvenidas a la app",
                    message="A partir de hoy registramos entrada y salida desde el celular. Cualquier duda, con Marisol.",
                    notice_type="recordatorio",
                    author_id=manager.id,
                    daycare_id=cumbres.id,
                    recipients=[NoticeRecipient(user_id=employee.id, is_read=False) for employee in employees],
                )
            )

        db.commit()
        users = db.scalar(select(func.count()).select_from(User))
    print(f"Seed done: {len(DAYCARES)} daycares, {users} users.")
    print('Try the usernames "ana.torres", "marisol.garcia" or "direccion" with the SEED_PASSWORD password.')


if __name__ == "__main__":
    main()
