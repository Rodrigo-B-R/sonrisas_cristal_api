"""/notices: managers (and directors) send notices and see who confirmed reading them.

A director can write to one daycare or send a general notice (no daycare) to all of them.
Everyone reads what reached them in /notices/inbox and confirms with POST /notices/{id}/read.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import joinedload

from app.constants import NOTICE_TYPE_TO_DB, ROLE_TO_DB
from app.dependencies import CurrentUser, DbSession, ManagerOrDirector, get_current_user
from app.errors import ApiError
from app.models import Daycare, Notice, NoticeRecipient, Role, Schedule, ScheduleDay, User
from app.schemas import (
    EmployeeNoticeOut,
    ManagerNoticeOut,
    NoticeBaseOut,
    NoticeDetailOut,
    NoticeIn,
    ReadReceiptOut,
)
from app.timeutils import now_utc, today

router = APIRouter(prefix="/notices", tags=["Notices"], dependencies=[Depends(get_current_user)])


def _visible_to(user: User, daycare_id: int | None = None) -> list:
    """Notices a manager can see: their daycare's and the general ones. A director: all, or one daycare's."""
    if user.role_code == "director":
        return [Notice.daycare_id == daycare_id] if daycare_id is not None else []
    return [or_(Notice.daycare_id == user.daycare_id, Notice.daycare_id.is_(None))]


def _can_see(user: User, notice: Notice) -> bool:
    return user.role_code == "director" or notice.daycare_id is None or notice.daycare_id == user.daycare_id


def _recipient_filter(user: User) -> list:
    """From a general notice, a manager only sees the readers of their own daycare."""
    return [] if user.role_code == "director" else [User.daycare_id == user.daycare_id]


def _base(notice: Notice) -> dict:
    return NoticeBaseOut.model_validate(notice).model_dump()


# ── What reached me ──────────────────────────────────────────────────


def _inbox_item(receipt: NoticeRecipient) -> dict:
    return {**_base(receipt.notice), "read": receipt.is_read, "read_at": receipt.read_at}


@router.get("/inbox", response_model=list[EmployeeNoticeOut])
def inbox(user: CurrentUser, db: DbSession):
    """The notices that reached me, with whether I read them."""
    receipts = db.scalars(
        select(NoticeRecipient)
        .where(NoticeRecipient.user_id == user.id)
        .options(joinedload(NoticeRecipient.notice).joinedload(Notice.author))
        .order_by(NoticeRecipient.notice_id.desc())
    ).all()
    return [_inbox_item(receipt) for receipt in receipts]


@router.get("/inbox/{notice_id}", response_model=EmployeeNoticeOut)
def inbox_item(notice_id: int, user: CurrentUser, db: DbSession):
    receipt = db.scalars(
        select(NoticeRecipient)
        .where(NoticeRecipient.notice_id == notice_id, NoticeRecipient.user_id == user.id)
        .options(joinedload(NoticeRecipient.notice).joinedload(Notice.author))
    ).first()
    if receipt is None:
        raise ApiError(404, "Not found")
    return _inbox_item(receipt)


@router.post("/{notice_id}/read", response_model=ReadReceiptOut)
def confirm_read(notice_id: int, user: CurrentUser, db: DbSession):
    """I confirm I read it. If I already had, the first time stays."""
    receipt = db.get(NoticeRecipient, (notice_id, user.id))
    if receipt is None:
        raise ApiError(404, "This notice is not for you")
    if not receipt.is_read:
        receipt.is_read, receipt.read_at = True, now_utc()
        db.commit()
    return {"notice_id": notice_id, "read": receipt.is_read, "read_at": receipt.read_at}


# ── Manager and director ─────────────────────────────────────────────


def _counts(db, user: User, notice_ids: list[int]) -> dict[int, tuple[int, int]]:
    """notice id -> (recipients, confirmed): the "9 of 14 confirmed" of the list."""
    if not notice_ids:
        return {}
    rows = db.execute(
        select(
            NoticeRecipient.notice_id,
            func.count(),
            func.coalesce(func.sum(case((NoticeRecipient.is_read.is_(True), 1), else_=0)), 0),
        )
        .join(User, User.id == NoticeRecipient.user_id)
        .where(NoticeRecipient.notice_id.in_(notice_ids), *_recipient_filter(user))
        .group_by(NoticeRecipient.notice_id)
    ).all()
    return {notice_id: (total, int(confirmed)) for notice_id, total, confirmed in rows}


def _manager_item(notice: Notice, counts: tuple[int, int], mine: NoticeRecipient | None) -> dict:
    total, confirmed = counts
    item = {**_base(notice), "recipient_count": total, "confirmed_count": confirmed}
    if mine is not None:
        item.update(read=mine.is_read, read_at=mine.read_at)
    return item


@router.get("", response_model=list[ManagerNoticeOut])
def list_notices(
    user: ManagerOrDirector,
    db: DbSession,
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    notices = db.scalars(
        select(Notice).where(*_visible_to(user, daycare_id)).options(joinedload(Notice.author)).order_by(Notice.id.desc())
    ).all()
    ids = [notice.id for notice in notices]
    counts = _counts(db, user, ids)
    mine = {
        receipt.notice_id: receipt
        for receipt in db.scalars(
            select(NoticeRecipient).where(NoticeRecipient.user_id == user.id, NoticeRecipient.notice_id.in_(ids))
        )
    }
    return [_manager_item(n, counts.get(n.id, (0, 0)), mine.get(n.id)) for n in notices]


@router.get("/{notice_id}", response_model=NoticeDetailOut)
def get_notice(notice_id: int, user: ManagerOrDirector, db: DbSession):
    """The notice with who confirmed and who is pending (the "reading status" screen)."""
    notice = db.scalars(
        select(Notice).where(Notice.id == notice_id).options(joinedload(Notice.author))
    ).first()
    if notice is None or not _can_see(user, notice):
        raise ApiError(404, "Not found")
    receipts = db.scalars(
        select(NoticeRecipient)
        .join(User, User.id == NoticeRecipient.user_id)
        .where(NoticeRecipient.notice_id == notice_id, *_recipient_filter(user))
        .options(joinedload(NoticeRecipient.user))
    ).all()
    confirmed = sorted((r for r in receipts if r.is_read), key=lambda r: r.read_at or now_utc())
    return {
        **_base(notice),
        "recipient_count": len(receipts),
        "confirmed": [{"id": r.user.id, "name": r.user.name, "read_at": r.read_at} for r in confirmed],
        "pending": [{"id": r.user.id, "name": r.user.name} for r in receipts if not r.is_read],
    }


def _works_today_with(**column) -> object:
    """People whose schedule, valid today, includes a day with that shift or room."""
    day = today()
    return User.schedules.any(
        and_(
            Schedule.valid_from <= day,
            Schedule.valid_until >= day,
            Schedule.days.any(and_(*(getattr(ScheduleDay, name) == value for name, value in column.items()))),
        )
    )


@router.post("", response_model=ManagerNoticeOut, status_code=201)
def create_notice(body: NoticeIn, user: ManagerOrDirector, db: DbSession):
    """A manager writes to their own daycare. A director writes to one (daycareId) or to all (no daycareId)."""
    if user.role_code == "director":
        daycare_id = body.daycare_id
        if daycare_id is not None and db.get(Daycare, daycare_id) is None:
            raise ApiError(400, "Daycare not found")
    else:
        if body.daycare_id not in (None, user.daycare_id):
            raise ApiError(403, "Only a director can choose the daycare")
        daycare_id = user.daycare_id

    stmt = (
        select(User.id)
        .join(User.role)
        .where(User.is_active.is_(True), User.id != user.id, Role.name != ROLE_TO_DB["director"])
    )
    if daycare_id is not None:
        stmt = stmt.where(User.daycare_id == daycare_id)
    if body.target == "shift":
        if body.shift_id is None:
            raise ApiError(400, "Missing shiftId")
        stmt = stmt.where(_works_today_with(shift_id=body.shift_id))
    elif body.target == "room":
        if body.room_id is None:
            raise ApiError(400, "Missing roomId")
        stmt = stmt.where(_works_today_with(room_id=body.room_id))
    elif body.target == "people":
        if not body.user_ids:
            raise ApiError(400, "Missing userIds (a list with at least one id)")
        stmt = stmt.where(User.id.in_(body.user_ids))  # still inside the daycare filter above
    recipient_ids = db.scalars(stmt).all()
    if not recipient_ids:
        raise ApiError(400, "Nobody would receive this notice")

    notice = Notice(
        subject=body.subject,
        message=body.message,
        notice_type=NOTICE_TYPE_TO_DB[body.notice_type],
        requires_confirmation=body.requires_confirmation,
        author_id=user.id,
        daycare_id=daycare_id,  # None = general
        recipients=[NoticeRecipient(user_id=recipient_id, is_read=False) for recipient_id in recipient_ids],
    )
    db.add(notice)
    db.commit()
    return _manager_item(notice, (len(recipient_ids), 0), None)
