"""/catalogs: roles, positions, shifts, termination reasons and absence reasons."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.access import require_found
from app.dependencies import DbSession, DirectorOnly, get_current_user
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


def _all(db, model):
    return db.scalars(select(model).order_by(model.id)).all()


@router.get("", response_model=CatalogsOut)
def get_catalogs(db: DbSession):
    return {
        "roles": _all(db, Role),
        "positions": _all(db, Position),
        "shifts": _all(db, Shift),
        "termination_reasons": _all(db, TerminationReason),
        "absence_reasons": _all(db, AbsenceReason),
    }


@router.post("/absence-reasons", response_model=AbsenceReasonOut, status_code=201)
def create_absence_reason(body: AbsenceReasonIn, user: DirectorOnly, db: DbSession):
    """409 if the description already exists."""
    reason = AbsenceReason(description=body.description)
    db.add(reason)
    db.commit()
    return reason


@router.post("/positions", response_model=PositionOut, status_code=201)
def create_position(body: NameIn, user: DirectorOnly, db: DbSession):
    position = Position(name=body.name)
    db.add(position)
    db.commit()
    return position


@router.post("/termination-reasons", response_model=TerminationReasonOut, status_code=201)
def create_termination_reason(body: NameIn, user: DirectorOnly, db: DbSession):
    reason = TerminationReason(name=body.name)
    db.add(reason)
    db.commit()
    return reason


@router.put("/shifts/{shift_id}", response_model=ShiftOut)
def update_shift(shift_id: int, body: ShiftUpdateIn, user: DirectorOnly, db: DbSession):
    shift = require_found(db.get(Shift, shift_id))
    if body.name is not None:
        shift.name = body.name
    if body.start_time is not None:
        shift.start_time = body.start_time
    if body.end_time is not None:
        shift.end_time = body.end_time
    db.commit()
    return shift
