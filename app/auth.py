"""User authentication and login activity logging."""

import hmac
import logging
from collections import deque
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, SecretStr

logger = logging.getLogger(__name__)

# Dedicated logger for user login audit trail
audit_logger = logging.getLogger("app.auth.audit")

router = APIRouter(tags=["auth"])

_MAX_LOGIN_RECORDS = 1000

# In-memory store for login records (demo purposes) with bounded size
login_records: deque["LoginRecord"] = deque(maxlen=_MAX_LOGIN_RECORDS)


class LoginRequest(BaseModel):
    """Payload for user login."""

    username: str
    password: SecretStr


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


@router.post("/auth/login", status_code=200)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate a user and log the attempt details."""
    stored_password = _DEMO_USERS.get(body.username)
    password_value = body.password.get_secret_value()

    if stored_password is None:
        hmac.compare_digest(password_value, "dummy")
        _record_login(body.username, request, success=False, failure_reason="invalid credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login failed \u2014 invalid credentials",
        )

    if not hmac.compare_digest(password_value, stored_password):
        _record_login(body.username, request, success=False, failure_reason="invalid credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login failed \u2014 invalid credentials",
        )

    record = _record_login(body.username, request, success=True)
    return LoginResponse(
        message="Login successful",
        username=body.username,
        logged_in_at=record.timestamp,
    )


_security = HTTPBasic()


def _verify_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    """Require valid admin credentials to access login records."""
    correct_username = hmac.compare_digest(credentials.username, "admin")
    correct_password = hmac.compare_digest(credentials.password, _DEMO_USERS["admin"])
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get(
    "/auth/login-records",
    response_model=list[LoginRecord],
    dependencies=[Depends(_verify_admin)],
)
async def list_login_records(limit: int = 50) -> list[LoginRecord]:
    """Return recent login records (most recent first). Requires admin authentication."""
    sorted_records = sorted(login_records, key=lambda r: r.timestamp, reverse=True)
    return sorted_records[:limit]
