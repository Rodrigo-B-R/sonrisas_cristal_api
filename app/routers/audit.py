"""/audit: who changed what. The database triggers fill it; the API only reads it (directors only)."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.dependencies import DbSession, get_current_user, require_role
from app.models import AuditLog
from app.schemas import AuditOut
from app.timeutils import day_end, day_start, read_period

router = APIRouter(
    prefix="/audit",
    tags=["Audit"],
    dependencies=[Depends(get_current_user), Depends(require_role("director"))],
)


@router.get("", response_model=list[AuditOut])
def list_changes(
    db: DbSession,
    start_date: date | None = Query(None, alias="startDate", description="Default: Monday of this week"),
    end_date: date | None = Query(None, alias="endDate", description="Default: today"),
    table: Literal["registro_entradas", "asistencia"] | None = None,
    record_id: int | None = Query(None, alias="recordId"),
    user_id: int | None = Query(None, alias="userId"),
):
    """The last 500 changes of the period, newest first."""
    start, end = read_period(start_date, end_date)
    stmt = (
        select(AuditLog)
        .where(AuditLog.created_at >= day_start(start), AuditLog.created_at <= day_end(end))
        .options(joinedload(AuditLog.user))
        .order_by(AuditLog.id.desc())
        .limit(500)
    )
    if table:
        stmt = stmt.where(AuditLog.table_name == table)
    if record_id is not None:
        stmt = stmt.where(AuditLog.record_id == record_id)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    return [
        {
            "id": change.id,
            "user_id": change.user_id,
            "action": change.action,
            "table": change.table_name,
            "record_id": change.record_id,
            "previous_data": change.previous_data,
            "new_data": change.new_data,
            "created_at": change.created_at,
            "user": change.user,
        }
        for change in db.scalars(stmt)
    ]
