"""/corrections: an employee asks to fix the time of a record; a manager approves or rejects it.

The record only changes when the correction is approved, in the same transaction.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.access import can_access_daycare, daycare_scope
from app.constants import CORRECTION_TO_DB
from app.database import set_audit_user
from app.dependencies import CurrentUser, DbSession, EmployeeOrManager, ManagerOnly, get_current_user
from app.errors import ApiError
from app.models import Correction, TimeRecord, User
from app.schemas import CorrectionIn, CorrectionOut
from app.services import records as record_service
from app.timeutils import now_utc, read_timestamp

router = APIRouter(prefix="/corrections", tags=["Corrections"], dependencies=[Depends(get_current_user)])

PENDING = CORRECTION_TO_DB["pending"]


def _options():
    return (
        joinedload(Correction.record).joinedload(TimeRecord.room),
        joinedload(Correction.record).joinedload(TimeRecord.shift),
        joinedload(Correction.record).joinedload(TimeRecord.user),
        joinedload(Correction.requested_by),
        joinedload(Correction.resolved_by),
    )


@router.get("", response_model=list[CorrectionOut])
def list_corrections(
    user: CurrentUser,
    db: DbSession,
    status: Literal["pending", "approved", "rejected"] | None = None,
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    stmt = select(Correction).options(*_options()).order_by(Correction.created_at.desc())
    if status:
        stmt = stmt.where(Correction.status == CORRECTION_TO_DB[status])
    if user.role_code == "employee":
        stmt = stmt.where(Correction.record.has(TimeRecord.user_id == user.id))
    else:
        scope = daycare_scope(user, daycare_id)
        if scope is not None:
            stmt = stmt.where(Correction.record.has(TimeRecord.user.has(User.daycare_id == scope)))
    return db.scalars(stmt).unique().all()


@router.post("", response_model=CorrectionOut, status_code=201)
def request_correction(body: CorrectionIn, user: EmployeeOrManager, db: DbSession):
    """An employee asks to fix one of their own records; a manager, one of their daycare's."""
    record = db.scalars(
        select(TimeRecord).where(TimeRecord.id == body.record_id).options(joinedload(TimeRecord.user))
    ).first()
    allowed = record is not None and (
        record.user_id == user.id if user.role_code == "employee" else can_access_daycare(user, record.user.daycare_id)
    )
    if not allowed:
        raise ApiError(404, "Record not found")

    pending = db.scalars(
        select(Correction).where(Correction.record_id == record.id, Correction.status == PENDING)
    ).first()
    if pending:
        raise ApiError(409, "That record already has a pending correction", correctionId=pending.id)

    proposed = record_service.propose_times(
        record,
        read_timestamp(body.clock_in_at) if body.clock_in_at is not None else None,
        read_timestamp(body.clock_out_at) if body.clock_out_at is not None else None,
        "clock_out_at" in body.model_fields_set,
    )
    set_audit_user(db, user.id)
    correction = Correction(
        record_id=record.id,
        previous_clock_in=proposed.previous_clock_in,
        previous_clock_out=proposed.previous_clock_out,
        proposed_clock_in=proposed.proposed_clock_in,
        proposed_clock_out=proposed.proposed_clock_out,
        reason=body.reason,
        requested_by_id=user.id,
    )
    db.add(correction)
    db.commit()
    return db.scalars(select(Correction).options(*_options()).where(Correction.id == correction.id)).unique().one()


def _resolve(db, user: User, correction_id: int, decision: Literal["approved", "rejected"]) -> Correction:
    correction = db.scalars(
        select(Correction)
        .options(joinedload(Correction.record).joinedload(TimeRecord.user))
        .where(Correction.id == correction_id)
    ).first()
    if correction is None or not can_access_daycare(user, correction.record.user.daycare_id):
        raise ApiError(404, "Correction not found")
    if correction.status != PENDING:
        raise ApiError(409, f"It was already {correction.status}")

    set_audit_user(db, user.id)
    if decision == "approved":
        correction.record.clock_in_at = correction.proposed_clock_in
        correction.record.clock_out_at = correction.proposed_clock_out
    correction.status = CORRECTION_TO_DB[decision]
    correction.resolved_by_id = user.id
    correction.resolved_at = now_utc()
    db.commit()
    return db.scalars(select(Correction).options(*_options()).where(Correction.id == correction_id)).unique().one()


@router.post("/{correction_id}/approve", response_model=CorrectionOut)
def approve_correction(correction_id: int, user: ManagerOnly, db: DbSession):
    return _resolve(db, user, correction_id, "approved")


@router.post("/{correction_id}/reject", response_model=CorrectionOut)
def reject_correction(correction_id: int, user: ManagerOnly, db: DbSession):
    return _resolve(db, user, correction_id, "rejected")
