"""/rooms: the manager administers the rooms of their daycare. There is no DELETE:
the database user of the API is not allowed to delete."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.access import daycare_scope, require_daycare_access, require_found
from app.dependencies import CurrentUser, DbSession, ManagerOnly, get_current_user
from app.models import Room
from app.schemas import RoomIn, RoomOut, RoomUpdateIn

router = APIRouter(prefix="/rooms", tags=["Rooms"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[RoomOut])
def list_rooms(
    user: CurrentUser,
    db: DbSession,
    daycare_id: int | None = Query(None, alias="daycareId", description="Directors only"),
):
    stmt = select(Room).order_by(Room.id)
    scope = daycare_scope(user, daycare_id)
    if scope is not None:
        stmt = stmt.where(Room.daycare_id == scope)
    return db.scalars(stmt).all()


@router.get("/{room_id}", response_model=RoomOut)
def get_room(room_id: int, user: CurrentUser, db: DbSession):
    room = require_found(db.get(Room, room_id), "Room not found")
    require_daycare_access(user, room.daycare_id, "Room not found")
    return room


@router.post("", response_model=RoomOut, status_code=201)
def create_room(body: RoomIn, user: ManagerOnly, db: DbSession):
    room = Room(name=body.name, min_staff=body.min_staff, daycare_id=user.daycare_id)
    db.add(room)
    db.commit()
    return room


@router.put("/{room_id}", response_model=RoomOut)
def update_room(room_id: int, body: RoomUpdateIn, user: ManagerOnly, db: DbSession):
    room = require_found(db.get(Room, room_id), "Room not found")
    require_daycare_access(user, room.daycare_id, "Room not found")
    if body.name is not None:
        room.name = body.name
    if body.min_staff is not None:
        room.min_staff = body.min_staff
    db.commit()
    return room
