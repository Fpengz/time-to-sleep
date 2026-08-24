from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["codex", "claude", "antigravity"]


class AccountStatus(StrEnum):
    LIVE = "live"
    CACHED = "cached"
    STALE = "stale"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"


class ErrorCode(StrEnum):
    NOT_CONFIGURED = "not_configured"
    NOT_AUTHENTICATED = "not_authenticated"
    AUTHENTICATION_EXPIRED = "authentication_expired"
    RATE_LIMITED = "rate_limited"
    PARSE_ERROR = "parse_error"
    TIMEOUT = "timeout"
    IDENTITY_MISMATCH = "identity_mismatch"
    NO_RECENT_DATA = "no_recent_data"


class AccountConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    provider: ProviderName
    email: str = Field(min_length=3)
    home: str = Field(min_length=1)
    warning_threshold: float = Field(default=80.0, ge=1.0, le=100.0)
    critical_threshold: float = Field(default=95.0, ge=1.0, le=100.0)

    @field_validator("id", "email", "home")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @property
    def expanded_home(self) -> str:
        return str(Path(self.home).expanduser())


class UsageWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    used_percent: Annotated[float, Field(ge=0, le=100)]
    window_minutes: int | None = Field(default=None, gt=0)
    resets_at: datetime | None = None

    @field_validator("resets_at")
    @classmethod
    def require_aware_reset(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("resets_at must be timezone-aware")
        return value


class UsageSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str = Field(min_length=1)
    provider: ProviderName
    configured_email: str = Field(min_length=3)
    observed_email: str | None = None
    status: AccountStatus
    source: str = Field(min_length=1)
    observed_at: datetime | None = None
    retrieved_at: datetime
    windows: list[UsageWindow] = Field(default_factory=list)
    plan_type: str | None = None
    message: str | None = None
    error_code: ErrorCode | None = None

    @field_validator("observed_at", "retrieved_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class LoginChallenge(BaseModel):
    attempt_id: str = Field(min_length=1)
    method: Literal["browser", "device_code"]
    status: Literal["pending", "succeeded", "failed", "cancelled", "expired"]
    auth_url: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    message: str | None = None


class LoginAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    method: Literal["browser", "device_code"]
    status: Literal["pending", "succeeded", "failed", "cancelled", "expired"]
    started_at: datetime
    expires_at: datetime
    observed_email: str | None = None
    message: str | None = None


class AccountStatusView(BaseModel):
    account_id: str
    provider: ProviderName
    configured_email: str
    configured_home: str
    ready: bool
    observed_email: str | None = None
    message: str | None = None


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    accounts: list[AccountConfig] = Field(min_length=1)


class AccountAnalytics(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    provider: ProviderName
    current_percent: float
    burn_rate_per_hour: float | None = None
    minutes_to_exhaustion: int | None = None
    status: AccountStatus
    recommended: bool = False
    recommendation_reason: str | None = None


class AnalyticsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    accounts: list[AccountAnalytics]
    suggestions: list[str] = Field(default_factory=list)
