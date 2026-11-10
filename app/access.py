"""Which daycares can a person see? Employees and managers: their own. Directors: all.

Use these in every query and every lookup by id, so data from another daycare never leaks.
When something belongs to another daycare the API answers 404 (not 403): it does not even
confirm that the id exists.
"""

from app.errors import ApiError
from app.models import User


def daycare_scope(user: User, requested_id: int | None = None) -> int | None:
    """The daycare id to filter by, or None for "all of them" (directors only).

    A director may ask for one with ?daycareId=. Everyone else is always pinned to their own.
    """
    if user.role_code == "director":
        return requested_id
    return user.daycare_id


def can_access_daycare(user: User, daycare_id: int | None) -> bool:
    return user.role_code == "director" or daycare_id == user.daycare_id


def require_daycare_access(user: User, daycare_id: int | None, what: str = "Not found") -> None:
    if not can_access_daycare(user, daycare_id):
        raise ApiError(404, what)


def require_found(value, message: str = "Not found"):
    """Returns the value, or answers 404 if it is None."""
    if value is None:
        raise ApiError(404, message)
    return value
