"""User authentication and login activity logging."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Dedicated logger for user login audit trail
audit_logger = logging.getLogger("app.auth.audit")

router = APIRouter(tags=["auth"])

# In-memory store for login records (demo purposes)
login_records: list["LoginRecord"] = []


class LoginRequest(BaseModel):
    """Payload for user login."""

    username: str
    password: str


class LoginRecord(BaseModel):
    """Captured details of a user login attempt."""

    username: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ip_address: str | None = None
    user_agent: str | None = None
    success: bool = True
    failure_reason: str | None = None


class LoginResponse(BaseModel):
    """Response returned after a login attempt."""

    message: str
    username: str
    logged_in_at: datetime


# Simple demo credentials — in production this would use a real auth backend
_DEMO_USERS: dict[str, str] = {
    "admin": "admin123",
    "operator": "operator123",
    "viewer": "viewer123",
}


def _record_login(
    username: str,
    request: Request,
    *,
    success: bool,
    failure_reason: str | None = None,
) -> LoginRecord:
    record = LoginRecord(
        username=username,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=success,
        failure_reason=failure_reason,
    )
    login_records.append(record)

    if success:
        audit_logger.info(
            "LOGIN_SUCCESS user=%s ip=%s user_agent=%s timestamp=%s",
            record.username,
            record.ip_address,
            record.user_agent,
            record.timestamp.isoformat(),
        )
    else:
        audit_logger.warning(
            "LOGIN_FAILURE user=%s ip=%s user_agent=%s reason=%s timestamp=%s",
            record.username,
            record.ip_address,
            record.user_agent,
            record.failure_reason,
            record.timestamp.isoformat(),
        )
    return record


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate a user and log the attempt details."""
    if body.username not in _DEMO_USERS:
        _record_login(body.username, request, success=False, failure_reason="unknown user")
        return LoginResponse(
            message="Login failed — unknown user",
            username=body.username,
            logged_in_at=datetime.now(UTC),
        )

    if _DEMO_USERS[body.username] != body.password:
        _record_login(body.username, request, success=False, failure_reason="invalid password")
        return LoginResponse(
            message="Login failed — invalid password",
            username=body.username,
            logged_in_at=datetime.now(UTC),
        )

    record = _record_login(body.username, request, success=True)
    return LoginResponse(
        message="Login successful",
        username=body.username,
        logged_in_at=record.timestamp,
    )


@router.get("/auth/login-records", response_model=list[LoginRecord])
async def list_login_records(limit: int = 50) -> list[LoginRecord]:
    """Return recent login records (most recent first)."""
    sorted_records = sorted(login_records, key=lambda r: r.timestamp, reverse=True)
    return sorted_records[:limit]
