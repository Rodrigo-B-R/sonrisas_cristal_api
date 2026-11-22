"""/catalogs: roles, positions, shifts, termination reasons and absence reasons."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.access import require_found
from app.dependencies import CurrentUser, DbSession, get_current_user
from app.models import AbsenceReason, Position, Role, Shift, TerminationReason
from app.schemas import (
    AbsenceReasonIn,
    AbsenceReasonOut,
    CatalogsOut,
    NameIn,
    PositionOut,
    ShiftOut,
    ShiftUpdateIn,
    TerminationReasonOut,
)

router = APIRouter(prefix="/catalogs", tags=["Catalogs"], dependencies=[Depends(get_current_user)])


def _all(db, model, order):
    """Every row, in a stable order (ids are random UUIDs, so they cannot be the order)."""
    return db.scalars(select(model).order_by(order)).all()


@router.get("", response_model=CatalogsOut)
def get_catalogs(db: DbSession):
    return {
        "roles": _all(db, Role, Role.name),
        "positions": _all(db, Position, Position.name),
        "shifts": _all(db, Shift, Shift.start_time),  # morning before afternoon
        "termination_reasons": _all(db, TerminationReason, TerminationReason.name),
        "absence_reasons": _all(db, AbsenceReason, AbsenceReason.description),
    }


@router.post("/absence-reasons", response_model=AbsenceReasonOut, status_code=201)
def create_absence_reason(body: AbsenceReasonIn, user: CurrentUser, db: DbSession):
    """409 if the description already exists."""
    reason = AbsenceReason(description=body.description)
    db.add(reason)
    db.commit()
    return reason


@router.post("/positions", response_model=PositionOut, status_code=201)
def create_position(body: NameIn, user: CurrentUser, db: DbSession):
    position = Position(name=body.name)
    db.add(position)
    db.commit()
    return position


@router.post("/termination-reasons", response_model=TerminationReasonOut, status_code=201)
def create_termination_reason(body: NameIn, user: CurrentUser, db: DbSession):
    reason = TerminationReason(name=body.name)
    db.add(reason)
    db.commit()
    return reason


@router.put("/shifts/{shift_id}", response_model=ShiftOut)
def update_shift(shift_id: UUID, body: ShiftUpdateIn, user: CurrentUser, db: DbSession):
    shift = require_found(db.get(Shift, shift_id))
    if body.name is not None:
        shift.name = body.name
    if body.start_time is not None:
        shift.start_time = body.start_time
    if body.end_time is not None:
        shift.end_time = body.end_time
    db.commit()
    return shift
