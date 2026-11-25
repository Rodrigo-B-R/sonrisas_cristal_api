"""/catalogs: roles, positions, shifts, termination reasons and absence reasons."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.dependencies import DbSession, get_current_user
from app.models import AbsenceReason, Position, Role, Shift, TerminationReason
from app.schemas import CatalogsOut

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
