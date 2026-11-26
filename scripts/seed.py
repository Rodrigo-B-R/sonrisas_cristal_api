"""python -m scripts.seed

Test data. Safe to run several times: it does not duplicate anything. Every account gets its OWN
random password (valid under the app's password rules); they are printed once at the end, so copy
them. Running it again generates new ones. NEVER run it against production.

The catalog values (roles, positions, rooms...) and the people are sample business data in
Spanish, like the daycares themselves. The roles are stored the way the database expects
them (empleada, responsable, direccion).
"""

from datetime import date, time

from sqlalchemy import func, select

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
from app.security import hash_password, password_problems, temporary_password

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

# One director for the whole company (works from Cumbres), one manager and two employees per daycare.
DIRECTOR = ("direccion", "Dirección General")

# daycare -> (username, name)
MANAGERS = {
    "Cumbres": ("marisol.garcia", "Marisol García"),
    "San Nicolás": ("andrea.salinas", "Andrea Salinas"),
    "Apodaca": ("patricia.nunez", "Patricia Núñez"),
    "Guadalupe": ("veronica.cantu", "Verónica Cantú"),
    "Escobedo": ("gabriela.rios", "Gabriela Ríos"),
}

# daycare -> [(username, name, position, room, week)]
# A week from Monday to Sunday: M = morning, V = evening, · = day off
EMPLOYEES = {
    "Cumbres": [
        ("ana.torres", "Ana Torres", "Maestra titular", "Maternal A", "MMMM···"),
        ("lucia.herrera", "Lucía Herrera", "Asistente", "Lactantes", "M·MMMM·"),
    ],
    "San Nicolás": [
        ("carmen.ruiz", "Carmen Ruiz", "Maestra titular", "Maternal B", "VVVV·V·"),
        ("sofia.diaz", "Sofía Díaz", "Asistente", "Preescolar", "MM·MM··"),
    ],
    "Apodaca": [
        ("paola.reyes", "Paola Reyes", "Maestra titular", "Lactantes", "·MMMM·V"),
        ("rosa.medina", "Rosa Medina", "Auxiliar", "Maternal A", "MMMMM··"),
    ],
    "Guadalupe": [
        ("maria.lopez", "María López", "Maestra titular", "Preescolar", "MMM·M··"),
        ("elena.vargas", "Elena Vargas", "Asistente", "Maternal B", "VVV·VV·"),
    ],
    "Escobedo": [
        ("laura.campos", "Laura Campos", "Maestra titular", "Maternal A", "MMMM·M·"),
        ("diana.flores", "Diana Flores", "Auxiliar", "Lactantes", "·VVVV·V"),
    ],
}


def new_password() -> str:
    """A random password that also passes the app's own password rules."""
    while True:
        password = temporary_password()
        if not password_problems(password):
            return password


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
        director: User | None = None
        counter = 0
        credentials: list[tuple[str, str, str, str]] = []  # (daycare, role, username, password)

        def create_user(username: str, name: str, role: str, position: str, daycare: Daycare) -> User:
            nonlocal counter
            counter += 1
            data = dict(
                name=name,
                email=f"{username}@sonrisascristal.mx",
                phone=f"81 1000 {counter:04d}",
                role_id=roles[role].id,
                position_id=positions[position].id,
                daycare_id=daycare.id,
            )
            password = new_password()
            user = db.scalars(select(User).where(User.username == username)).first()
            if user is None:
                user = User(username=username, password_hash=hash_password(password), is_active=True, **data)
                db.add(user)
            else:  # it also resets the password and reactivates the account
                for key, value in data.items():
                    setattr(user, key, value)
                user.password_hash, user.is_active = hash_password(password), True
            db.flush()
            credentials.append((daycare.name, role, username, password))
            has_hire = db.scalars(select(Movement).where(Movement.user_id == user.id, Movement.type == "alta")).first()
            if not has_hire:
                db.add(
                    Movement(
                        type="alta",
                        date=HIRE_DATE,
                        user_id=user.id,
                        done_by_id=(director or user).id,
                        destination_daycare_id=daycare.id,
                    )
                )
            return user

        director = create_user(*DIRECTOR, "director", "Dirección", daycares["Cumbres"])

        for daycare_name, daycare in daycares.items():
            rooms = {room.name: room for room in db.scalars(select(Room).where(Room.daycare_id == daycare.id))}
            manager = create_user(*MANAGERS[daycare_name], "manager", "Responsable de estancia", daycare)

            employees = []
            for username, name, position, room, week in EMPLOYEES[daycare_name]:
                employee = create_user(username, name, "employee", position, daycare)
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

            if not db.scalars(select(Notice).where(Notice.daycare_id == daycare.id)).first():
                db.add(
                    Notice(
                        subject="Bienvenidas a la app",
                        message=f"A partir de hoy registramos entrada y salida desde el celular. Cualquier duda, con {manager.name}.",
                        notice_type="recordatorio",
                        author_id=manager.id,
                        daycare_id=daycare.id,
                        recipients=[NoticeRecipient(user_id=employee.id, is_read=False) for employee in employees],
                    )
                )

        db.commit()
        users = db.scalar(select(func.count()).select_from(User))
    print(f"Seed done: {len(DAYCARES)} daycares, {users} users.")
    print("\nCredentials (shown only now; save them):")
    print(f"{'Daycare':<14}{'Role':<10}{'Username':<18}Password")
    for daycare_name, role, username, password in credentials:
        print(f"{daycare_name:<14}{role:<10}{username:<18}{password}")


if __name__ == "__main__":
    main()
