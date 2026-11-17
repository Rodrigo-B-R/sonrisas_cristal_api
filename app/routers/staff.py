"""/staff: people, hires, terminations and transfers. Each one is saved in movements.

Managers and directors only. A manager works inside their own daycare, only changes employees
(a director can change anyone) and never sees directors.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.access import can_access_daycare, daycare_scope
from app.constants import MOVEMENT_TO_DB, ROLE_TO_DB
from app.dependencies import DbSession, ManagerOrDirector, require_role
from app.errors import ApiError
from app.logging_config import security_event
from app.models import Daycare, Movement, Position, Role, TerminationReason, User
from app.schemas import (
    MovementOut,
    StaffCreatedOut,
    StaffCreateIn,
    StaffDetailOut,
    StaffUpdateIn,
    TemporaryPasswordOut,
    TerminateIn,
    TransferIn,
    UserOut,
)
from app.security import get_client_ip, hash_password, password_problems, temporary_password
from app.services.schedules import current_schedule, schedule_load_options
from app.timeutils import today

router = APIRouter(
    prefix="/staff",
    tags=["Staff"],
    dependencies=[Depends(require_role("manager", "director"))],
)

HIRE = MOVEMENT_TO_DB["hire"]
TERMINATION = MOVEMENT_TO_DB["termination"]
TRANSFER = MOVEMENT_TO_DB["transfer"]

_person_options = (
    selectinload(User.role),
    selectinload(User.position),
    selectinload(User.daycare),
    selectinload(User.schedules).options(schedule_load_options()),
    selectinload(User.movements).selectinload(Movement.termination_reason),
)


def _can_see(user: User, person: User) -> bool:
    """Same daycare (a director: any), and a manager never sees directors."""
    if not can_access_daycare(user, person.daycare_id):
        return False
    return user.role_code == "director" or person.role_code != "director"


def find_person(db, user: User, person_id: int) -> User:
    person = db.scalars(select(User).options(*_person_options).where(User.id == person_id)).first()
    if person is None or not _can_see(user, person):
        raise ApiError(404, "Not found")
    return person


def _require_can_modify(user: User, person: User, message: str) -> None:
    """A manager only modifies employees; a director modifies anyone."""
    if user.role_code != "director" and person.role_code != "employee":
        raise ApiError(403, message)


def _log(request: Request, event: str, user: User, person: User, **fields) -> None:
    security_event(
        event,
        level=logging.INFO,
        by_user_id=user.id,
        target_user_id=person.id,
        ip=get_client_ip(request),
        **fields,
    )


@router.get("", response_model=list[UserOut])
def list_staff(
    user: ManagerOrDirector,
    db: DbSession,
    active: Literal["true", "false", "all"] = Query("true", description="true: active staff, false: terminated, all: both"),
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    stmt = (
        select(User)
        .join(User.role)
        .options(selectinload(User.role), selectinload(User.position), selectinload(User.daycare))
        .order_by(User.name)
    )
    scope = daycare_scope(user, daycare_id)
    if scope is not None:
        stmt = stmt.where(User.daycare_id == scope)
    if user.role_code != "director":
        stmt = stmt.where(Role.name != ROLE_TO_DB["director"])
    if active != "all":
        stmt = stmt.where(User.is_active.is_(active == "true"))
    return db.scalars(stmt).all()


@router.get("/{user_id}", response_model=StaffDetailOut)
def get_person(user_id: int, user: ManagerOrDirector, db: DbSession):
    """The profile with today's schedule and the history of movements."""
    person = find_person(db, user, user_id)
    data = UserOut.model_validate(person).model_dump()
    data["movements"] = [
        MovementOut.model_validate(m) for m in sorted(person.movements, key=lambda m: m.id, reverse=True)
    ]
    data["current_schedule"] = current_schedule(person.schedules, today())
    return data


@router.post("", response_model=StaffCreatedOut, status_code=201)
def create_person(request: Request, body: StaffCreateIn, user: ManagerOrDirector, db: DbSession):
    """A manager creates employees in their own daycare. A director also sends role and daycareId.

    Without a password a temporary one is generated; it is shown ONCE so the manager can give it
    to the person, who then changes it.
    """
    is_director = user.role_code == "director"
    if not is_director and (body.role not in (None, "employee") or body.daycare_id not in (None, user.daycare_id)):
        raise ApiError(403, "Only a director can choose the role or the daycare")
    role_name = (body.role or "employee") if is_director else "employee"
    daycare_id = body.daycare_id if is_director else user.daycare_id
    if not daycare_id:
        raise ApiError(400, "Missing daycareId")
    if body.password is not None and (problems := password_problems(body.password)):
        raise ApiError(400, "The password does not meet the requirements", missing=problems)

    role = db.scalars(select(Role).where(Role.name == ROLE_TO_DB[role_name])).first()
    position = db.get(Position, body.position_id)
    daycare = db.get(Daycare, daycare_id)
    if not (role and position and daycare):
        raise ApiError(400, "The role, position or daycare do not exist")

    temporary = body.password or temporary_password()
    person = User(
        name=body.name,
        username=body.username,
        email=body.email,
        phone=body.phone,
        is_active=True,
        password_hash=hash_password(temporary),
        role=role,
        position=position,
        daycare=daycare,
    )
    db.add(person)
    db.flush()
    db.add(
        Movement(
            type=HIRE,
            date=body.hire_date or today(),
            user_id=person.id,
            done_by_id=user.id,
            destination_daycare_id=daycare.id,
        )
    )
    db.commit()
    _log(request, "staff_created", user, person, role=role_name, daycare_id=daycare.id)
    data = UserOut.model_validate(person).model_dump()
    data["temporary_password"] = temporary
    return data


@router.put("/{user_id}", response_model=UserOut)
def update_person(request: Request, user_id: int, body: StaffUpdateIn, user: ManagerOrDirector, db: DbSession):
    person = find_person(db, user, user_id)
    _require_can_modify(user, person, "Only a director can modify another manager")
    if body.role is not None and user.role_code != "director":
        raise ApiError(403, "Only a director can change a role")

    new_role = None
    if body.role is not None:
        new_role = db.scalars(select(Role).where(Role.name == ROLE_TO_DB[body.role])).first()
        if new_role is None:
            raise ApiError(400, "Invalid role")
    if body.position_id is not None and db.get(Position, body.position_id) is None:
        raise ApiError(400, "That position does not exist")

    previous_role = person.role_code
    for field in ("name", "username", "email", "phone", "position_id"):
        value = getattr(body, field)
        if value is not None:
            setattr(person, field, value)
    if new_role is not None:
        person.role = new_role
    db.commit()
    if new_role is not None and previous_role != body.role:
        _log(request, "role_changed", user, person, previous_role=previous_role, new_role=body.role)
    db.refresh(person)
    return person


@router.post("/{user_id}/terminate", response_model=UserOut)
def terminate_person(request: Request, user_id: int, body: TerminateIn, user: ManagerOrDirector, db: DbSession):
    """The person is not deleted: they leave the active staff and their history stays."""
    person = find_person(db, user, user_id)
    _require_can_modify(user, person, "Only a director can terminate a manager")
    if not person.is_active:
        raise ApiError(409, "Already terminated")
    if person.id == user.id:
        raise ApiError(400, "You cannot terminate yourself")
    reason = db.get(TerminationReason, body.termination_reason_id)
    if reason is None:
        raise ApiError(400, "The termination reason does not exist (see GET /catalogs)")

    person.is_active = False
    db.add(
        Movement(
            type=TERMINATION,
            date=body.date or today(),
            notes=body.notes,
            user_id=person.id,
            done_by_id=user.id,
            termination_reason_id=reason.id,
            origin_daycare_id=person.daycare_id,
        )
    )
    db.commit()
    _log(request, "staff_terminated", user, person, reason_id=reason.id)
    return person


@router.post("/{user_id}/transfer", response_model=UserOut)
def transfer_person(request: Request, user_id: int, body: TransferIn, user: ManagerOrDirector, db: DbSession):
    person = find_person(db, user, user_id)
    _require_can_modify(user, person, "Only a director can transfer a manager")
    if not person.is_active:
        raise ApiError(409, "Already terminated")
    destination = db.get(Daycare, body.daycare_id)
    if destination is None:
        raise ApiError(400, "The daycare does not exist")
    if destination.id == person.daycare_id:
        raise ApiError(400, "Already in that daycare")

    origin_id = person.daycare_id
    person.daycare = destination
    db.add(
        Movement(
            type=TRANSFER,
            date=body.date or today(),
            notes=body.notes,
            user_id=person.id,
            done_by_id=user.id,
            origin_daycare_id=origin_id,
            destination_daycare_id=destination.id,
        )
    )
    db.commit()
    _log(request, "staff_transferred", user, person, origin_daycare_id=origin_id, destination_daycare_id=destination.id)
    return person


@router.post("/{user_id}/password", response_model=TemporaryPasswordOut)
def reset_password(request: Request, user_id: int, user: ManagerOrDirector, db: DbSession):
    """"Forgot your password? Ask your manager." Sets a new temporary password and shows it once."""
    person = find_person(db, user, user_id)
    _require_can_modify(user, person, "Only a director can reset the password of a manager")
    temporary = temporary_password()
    person.password_hash = hash_password(temporary)
    db.commit()
    _log(request, "password_reset", user, person)
    return {"temporary_password": temporary}
