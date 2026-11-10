"""Passwords, JWT, client IP, and brute-force protection for the login."""

import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address

import bcrypt
import jwt
from fastapi import Request
from slowapi import Limiter

from app.config import settings

# ── Passwords ────────────────────────────────────────────────────────

BCRYPT_ROUNDS = 12
MAX_PASSWORD_BYTES = 72  # bcrypt only reads the first 72 bytes


def _prepare(password: str) -> bytes:
    return password.encode("utf-8")[:MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("ascii"))
    except ValueError:
        return False


_dummy_hash: str | None = None


def waste_time_like_a_real_check(password: str) -> None:
    """Called when the username does not exist, so the answer takes as long as a real one.

    Without it, a fast "no" would tell an attacker which usernames exist.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password")
    verify_password(password, _dummy_hash)


def password_problems(new: str, previous: str | None = None) -> list[str]:
    """The requirements the new password does not meet (empty list = valid)."""
    problems = []
    if len(new) < 8:
        problems.append("At least 8 characters")
    if len(new.encode("utf-8")) > MAX_PASSWORD_BYTES:
        problems.append(f"At most {MAX_PASSWORD_BYTES} bytes")
    if not any(c.isupper() for c in new) or not any(c.islower() for c in new):
        problems.append("One uppercase and one lowercase letter")
    if not any(c.isdigit() for c in new):
        problems.append("One number")
    if previous is not None and new == previous:
        problems.append("Must be different from the previous one")
    return problems


def temporary_password() -> str:
    """Easy to read aloud: no 0/O and no 1/l/I."""
    letters = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(letters) for _ in range(8))


# ── JWT ──────────────────────────────────────────────────────────────
# The token only says WHO you are. Role, daycare and "is still active" are read from the
# database on every request, so a termination or a role change applies immediately.

ALGORITHM = "HS256"  # fixed on purpose: never let the token choose its own algorithm


def create_access_token(user_id: int) -> tuple[str, int]:
    """Returns the token and the seconds it lasts."""
    now = datetime.now(timezone.utc)
    lifetime = timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), int(lifetime.total_seconds())


def read_access_token(token: str) -> int:
    """Returns the user id, or raises jwt.PyJWTError."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    try:
        return int(payload["sub"])
    except (TypeError, ValueError) as error:
        raise jwt.InvalidTokenError("Invalid subject") from error


# ── Client IP (the API is behind a Cloudflare tunnel) ────────────────


def get_client_ip(request: Request) -> str:
    """The real client IP.

    Behind the tunnel, every request arrives from the tunnel container. Its headers are only
    believed when the request comes from a network listed in TRUSTED_PROXIES; otherwise anyone
    could write any IP in a header and skip the rate limit.
    """
    cached = getattr(request.state, "client_ip", None)
    if cached:
        return cached
    peer = request.client.host if request.client else "unknown"
    client = peer
    networks = settings.trusted_networks
    if networks:
        try:
            peer_address = ip_address(peer)
        except ValueError:
            peer_address = None
        if peer_address is not None and any(peer_address in network for network in networks):
            forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
            candidate = forwarded.split(",")[-1].strip()  # the last one is the one our proxy added
            try:
                client = str(ip_address(candidate))
            except ValueError:
                pass
    request.state.client_ip = client
    return client


# ── Rate limit per IP ────────────────────────────────────────────────

limiter = Limiter(
    key_func=get_client_ip,
    default_limits=[settings.default_rate_limit],
    enabled=settings.rate_limit_enabled,
)


# ── Lock an account after too many failed logins ─────────────────────


@dataclass
class _Attempts:
    failures: deque = field(default_factory=deque)
    locked_until: float = 0.0


class LoginGuard:
    """Counts failed logins per username (kept in memory: with several workers each has its own count).

    The IP rate limit stops one machine; this stops an attack on one account from many machines.
    The price is that someone can lock an account by failing on purpose; it unlocks by itself.
    """

    MAX_ENTRIES = 50_000

    def __init__(self, max_failures: int, window_seconds: int, lockout_seconds: int):
        self.max_failures = max_failures
        self.window = window_seconds
        self.lockout = lockout_seconds
        self._attempts: dict[str, _Attempts] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(username: str) -> str:
        return username.casefold()[:255]

    def seconds_locked(self, username: str) -> int:
        """0 if the account can try to log in; otherwise the seconds left."""
        with self._lock:
            attempts = self._attempts.get(self._key(username))
            if not attempts:
                return 0
            remaining = attempts.locked_until - time.monotonic()
            return int(remaining) + 1 if remaining > 0 else 0

    def register_failure(self, username: str) -> bool:
        """Returns True if this failure locked the account."""
        now = time.monotonic()
        with self._lock:
            if len(self._attempts) >= self.MAX_ENTRIES:
                self._forget_old(now)
            attempts = self._attempts.setdefault(self._key(username), _Attempts())
            while attempts.failures and now - attempts.failures[0] > self.window:
                attempts.failures.popleft()
            attempts.failures.append(now)
            if len(attempts.failures) >= self.max_failures:
                attempts.locked_until = now + self.lockout
                attempts.failures.clear()
                return True
            return False

    def register_success(self, username: str) -> None:
        with self._lock:
            self._attempts.pop(self._key(username), None)

    def _forget_old(self, now: float) -> None:
        self._attempts = {
            key: attempts
            for key, attempts in self._attempts.items()
            if attempts.locked_until > now or (attempts.failures and now - attempts.failures[-1] <= self.window)
        }
        if len(self._attempts) >= self.MAX_ENTRIES:
            self._attempts.clear()  # being attacked with random usernames: start over rather than grow


login_guard = LoginGuard(
    max_failures=settings.login_max_failures,
    window_seconds=settings.login_lockout_minutes * 60,
    lockout_seconds=settings.login_lockout_minutes * 60,
)
