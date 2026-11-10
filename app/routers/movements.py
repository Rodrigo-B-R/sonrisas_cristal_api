"""/movements: the history of hires, terminations and transfers (managers and directors)."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from app.access import daycare_scope
from app.constants import MOVEMENT_TO_DB
from app.dependencies import DbSession, ManagerOrDirector, require_role
from app.models import Movement
from app.schemas import MovementDetailOut
from app.timeutils import first_of_month, read_period, today

router = APIRouter(
    prefix="/movements",
    tags=["Movements"],
    dependencies=[Depends(require_role("manager", "director"))],
)


@router.get("", response_model=list[MovementDetailOut])
def list_movements(
    user: ManagerOrDirector,
    db: DbSession,
    start_date: date | None = Query(None, alias="startDate", description="Default: the first day of this month"),
    end_date: date | None = Query(None, alias="endDate"),
    type: Literal["hire", "termination", "transfer"] | None = None,
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    start, end = read_period(start_date, end_date, default_start=first_of_month(today()), max_days=400)
    stmt = (
        select(Movement)
        .where(Movement.date >= start, Movement.date <= end)
        .options(
            joinedload(Movement.user),
            joinedload(Movement.done_by),
            joinedload(Movement.termination_reason),
            joinedload(Movement.origin_daycare),
            joinedload(Movement.destination_daycare),
        )
        .order_by(Movement.date.desc(), Movement.id.desc())
    )
    if type:
        stmt = stmt.where(Movement.type == MOVEMENT_TO_DB[type])
    scope = daycare_scope(user, daycare_id)
    if scope is not None:
        stmt = stmt.where(or_(Movement.origin_daycare_id == scope, Movement.destination_daycare_id == scope))
    return db.scalars(stmt).all()
