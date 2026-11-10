"""FastAPI dependencies: who is calling, and may they do this?

This is the equivalent of the middlewares of the Node version:
  get_current_user    verificarToken  (and it also looks the user up in the database)
  require_role(...)   permitir(...)
Use the ready-made aliases at the bottom in a route:

    def create_room(user: ManagerOnly, db: DbSession): ...
"""

from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.errors import ApiError
from app.logging_config import security_event
from app.models import User
from app.security import get_client_ip, read_access_token

bearer_scheme = HTTPBearer(auto_error=False, description="Token from POST /login")

UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Reads the token and then loads the user from the database, on every request.

    The token only carries the user id. Role, daycare and "still active" come from the database,
    so a termination, a transfer or a role change takes effect on the very next request
    (the Node version trusted what the token said until it expired).
    """
    ip = get_client_ip(request)
    if credentials is None:
        security_event("auth_missing_token", ip=ip, method=request.method, path=request.url.path)
        raise ApiError(401, "Missing token", headers=UNAUTHORIZED)
    try:
        user_id = read_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        security_event("auth_expired_token", ip=ip, path=request.url.path)
        raise ApiError(401, "Token expired", headers=UNAUTHORIZED) from None
    except jwt.PyJWTError:
        security_event("auth_invalid_token", ip=ip, path=request.url.path)
        raise ApiError(401, "Invalid token", headers=UNAUTHORIZED) from None

    user = db.scalar(select(User).options(joinedload(User.role)).where(User.id == user_id))
    if user is None or not user.is_active:
        security_event("auth_inactive_user", user_id=user_id, ip=ip, path=request.url.path)
        raise ApiError(401, "Invalid token", headers=UNAUTHORIZED)  # same message: do not reveal why
    request.state.user_id = user.id
    return user


def require_role(*roles: str):
    """Only these roles (employee, manager, director) may call the route."""

    def check(request: Request, user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role_code not in roles:
            security_event(
                "access_denied",
                user_id=user.id,
                role=user.role_code,
                allowed=list(roles),
                method=request.method,
                path=request.url.path,
                ip=get_client_ip(request),
            )
            raise ApiError(403, "Your role cannot do this")
        return user

    return check


DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
EmployeeOrManager = Annotated[User, Depends(require_role("employee", "manager"))]
ManagerOnly = Annotated[User, Depends(require_role("manager"))]
ManagerOrDirector = Annotated[User, Depends(require_role("manager", "director"))]
DirectorOnly = Annotated[User, Depends(require_role("director"))]
