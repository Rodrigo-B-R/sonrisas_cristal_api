"""/daycares: anyone with a session can see them; only a director creates or changes them.

Each daycare has a location: the point and the radius (in meters) where the app considers
that a person "is at the daycare".
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from app.access import require_found
from app.dependencies import DbSession, DirectorOnly, get_current_user
from app.models import Daycare, Location
from app.schemas import DaycareIn, DaycareOut, DaycareUpdateIn

router = APIRouter(prefix="/daycares", tags=["Daycares"], dependencies=[Depends(get_current_user)])

_load = (joinedload(Daycare.location), selectinload(Daycare.rooms))


@router.get("", response_model=list[DaycareOut])
def list_daycares(db: DbSession):
    return db.scalars(select(Daycare).options(*_load).order_by(Daycare.id)).all()


@router.get("/{daycare_id}", response_model=DaycareOut)
def get_daycare(daycare_id: int, db: DbSession):
    daycare = db.scalars(select(Daycare).options(*_load).where(Daycare.id == daycare_id)).first()
    return require_found(daycare, "Daycare not found")


@router.post("", response_model=DaycareOut, status_code=201)
def create_daycare(body: DaycareIn, user: DirectorOnly, db: DbSession):
    location = Location(
        name=f"Daycare {body.name}",
        latitude=body.latitude,
        longitude=body.longitude,
        radius_meters=body.radius_meters,
    )
    daycare = Daycare(name=body.name, location=location)
    db.add(daycare)
    db.commit()
    return daycare


@router.put("/{daycare_id}", response_model=DaycareOut)
def update_daycare(daycare_id: int, body: DaycareUpdateIn, user: DirectorOnly, db: DbSession):
    daycare = require_found(
        db.scalars(select(Daycare).options(*_load).where(Daycare.id == daycare_id)).first(), "Daycare not found"
    )
    if body.name is not None:
        daycare.name = body.name
    if body.latitude is not None:
        daycare.location.latitude = body.latitude
    if body.longitude is not None:
        daycare.location.longitude = body.longitude
    if body.radius_meters is not None:
        daycare.location.radius_meters = body.radius_meters
    db.commit()
    return daycare
