"""Application settings, read from environment variables (and from .env)."""

from functools import lru_cache
from ipaddress import ip_network

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database. "postgres://" and "postgresql://" are accepted and rewritten for psycopg 3.
    database_url: str

    # Authentication
    jwt_secret: str = Field(min_length=32)
    jwt_expire_minutes: int = Field(60, ge=1)

    # Business rules
    tz: str = "America/Monterrey"  # decides what "today" is and when someone is late
    late_tolerance_minutes: int = Field(5, ge=0)

    # Runtime
    environment: str = "development"  # "production" turns off /docs and adds HSTS
    seed_password: str = "Cristal2026"
    metrics_token: str | None = None  # without it, GET /metrics is disabled

    # Brute-force protection (A07)
    login_rate_limit: str = "5/minute"  # per IP, on POST /login
    default_rate_limit: str = "300/minute"  # per IP, per route
    login_max_failures: int = Field(10, ge=1)  # failed logins per username...
    login_lockout_minutes: int = Field(15, ge=1)  # ...inside this window lock the account
    rate_limit_enabled: bool = True

    # The API sits behind a Cloudflare tunnel. Only requests that come from these
    # networks may tell us the real client IP (CF-Connecting-IP / X-Forwarded-For).
    # Comma-separated CIDRs, for example the Docker network of the tunnel container.
    trusted_proxies: str = ""

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, value: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @field_validator("jwt_secret")
    @classmethod
    def reject_placeholder_secret(cls, value: str) -> str:
        if "change-this" in value.lower() or "cambia-esto" in value.lower():
            raise ValueError("JWT_SECRET still has the example value; generate a real one")
        return value

    @field_validator("metrics_token")
    @classmethod
    def empty_token_is_none(cls, value: str | None) -> str | None:
        return value or None

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def trusted_networks(self) -> list:
        return [ip_network(item.strip(), strict=False) for item in self.trusted_proxies.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
