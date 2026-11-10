"""POST /login, and with a token: GET /profile and PUT /profile/password."""

import logging

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import settings
from app.dependencies import CurrentUser, DbSession
from app.errors import ApiError
from app.logging_config import clip, security_event
from app.models import User
from app.schemas import LoginIn, LoginOut, MessageOut, PasswordChangeIn, ProfileOut
from app.security import (
    create_access_token,
    get_client_ip,
    hash_password,
    limiter,
    login_guard,
    password_problems,
    verify_password,
    waste_time_like_a_real_check,
)

router = APIRouter(tags=["Session"])


@router.post("/login", response_model=LoginOut)
@limiter.limit(settings.login_rate_limit)
def login(request: Request, body: LoginIn, db: DbSession):
    """Username and password in, token out. Limited per IP, and an account is locked after too many failures."""
    ip = get_client_ip(request)
    username = body.username

    seconds_left = login_guard.seconds_locked(username)
    if seconds_left:
        security_event("login_locked", username=clip(username), ip=ip, seconds_left=seconds_left)
        raise ApiError(429, "Too many failed attempts. Try again later.", headers={"Retry-After": str(seconds_left)})

    user = db.scalar(select(User).options(joinedload(User.role)).where(User.username == username))
    if user is None:
        waste_time_like_a_real_check(body.password)  # so a wrong username is not faster than a wrong password
        reason = "unknown_user"
    elif not verify_password(body.password, user.password_hash):
        reason = "bad_password"
    elif not user.is_active:
        reason = "inactive_user"
    else:
        reason = None

    if reason:
        locked_now = login_guard.register_failure(username)
        security_event("login_failed", username=clip(username), reason=reason, ip=ip)
        if locked_now:
            security_event("account_locked", username=clip(username), ip=ip, minutes=settings.login_lockout_minutes)
        # Same answer for every reason: it does not say which part was wrong
        raise ApiError(401, "Invalid username or password")

    login_guard.register_success(username)
    token, expires_in = create_access_token(user.id)
    security_event("login_success", level=logging.INFO, user_id=user.id, role=user.role_code, ip=ip)
    return {
        "token": token,
        "expires_in": expires_in,
        "role": user.role_code,
        "user": {"id": user.id, "name": user.name, "daycare_id": user.daycare_id},
    }


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: CurrentUser):
    return user


@router.put("/profile/password", response_model=MessageOut)
def change_password(request: Request, body: PasswordChangeIn, user: CurrentUser, db: DbSession):
    if not verify_password(body.current_password, user.password_hash):
        security_event("password_change_failed", user_id=user.id, ip=get_client_ip(request))
        raise ApiError(401, "The current password is not correct")
    problems = password_problems(body.new_password, body.current_password)
    if problems:
        raise ApiError(400, "The password does not meet the requirements", missing=problems)
    user.password_hash = hash_password(body.new_password)
    db.commit()
    security_event("password_changed", level=logging.INFO, user_id=user.id, ip=get_client_ip(request))
    return {"message": "Password updated"}
