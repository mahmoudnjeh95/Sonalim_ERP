from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.cache import get_redis
from core.db import get_connection
from core.tenancy import TenantContext, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/core/auth", tags=["core.auth"])

# Short-lived access token + longer-lived, rotated-on-use refresh token: a
# stolen access token is only useful for ACCESS_TOKEN_TTL, and a stolen
# refresh token is caught the next time the legitimate client tries to use
# its (already-rotated) copy — see the reuse-detection branch in refresh().
ACCESS_TOKEN_TTL = timedelta(minutes=30)
REFRESH_TOKEN_TTL = timedelta(days=7)

LOGIN_LOCKOUT_THRESHOLD = 5
LOGIN_LOCKOUT_WINDOW_SECONDS = 15 * 60


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def _login_attempts_key(email: str) -> str:
    return f"core:auth:login_fail:{email}"


# Rate limiting is best-effort defense-in-depth, not the primary control —
# if Redis is unreachable (e.g. running the API without Docker for now),
# login should degrade to "unlimited attempts", not go down entirely.
def _too_many_recent_failures(email: str) -> bool:
    try:
        attempts = get_redis().get(_login_attempts_key(email))
    except Exception:
        logger.warning("login rate-limit check skipped: redis unavailable", exc_info=True)
        return False
    return attempts is not None and int(attempts) >= LOGIN_LOCKOUT_THRESHOLD


def _record_login_failure(email: str) -> None:
    try:
        redis_client = get_redis()
        key = _login_attempts_key(email)
        redis_client.incr(key)
        redis_client.expire(key, LOGIN_LOCKOUT_WINDOW_SECONDS)
    except Exception:
        logger.warning("login failure not recorded: redis unavailable", exc_info=True)


def _clear_login_failures(email: str) -> None:
    try:
        get_redis().delete(_login_attempts_key(email))
    except Exception:
        pass


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    refresh_token: str
    refresh_expires_at: str
    tenant_id: str
    user_id: str
    email: str
    permissions: list[str]


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


def _list_permissions(connection, *, user_id: str) -> list[str]:
    rows = connection.execute(
        "SELECT permission FROM core.user_permissions WHERE user_id = %s ORDER BY permission",
        (user_id,),
    ).fetchall()
    return [permission for (permission,) in rows]


def _issue_session(connection, *, user_id: str, tenant_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + ACCESS_TOKEN_TTL
    connection.execute(
        "INSERT INTO core.sessions (token, user_id, tenant_id, expires_at) VALUES (%s, %s, %s, %s)",
        (token, user_id, tenant_id, expires_at),
    )
    return token, expires_at


def _issue_refresh_token(connection, *, user_id: str, tenant_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + REFRESH_TOKEN_TTL
    connection.execute(
        "INSERT INTO core.refresh_tokens (token, user_id, tenant_id, expires_at) VALUES (%s, %s, %s, %s)",
        (token, user_id, tenant_id, expires_at),
    )
    return token, expires_at


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    if _too_many_recent_failures(body.email):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed login attempts; try again later",
        )

    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, tenant_id, password_hash FROM core.users WHERE email = %s",
            (body.email,),
        ).fetchone()

        if row is None or not verify_password(body.password, row[2]):
            _record_login_failure(body.email)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

        user_id, tenant_id, _ = row
        _clear_login_failures(body.email)

        token, expires_at = _issue_session(connection, user_id=user_id, tenant_id=tenant_id)
        refresh_token, refresh_expires_at = _issue_refresh_token(connection, user_id=user_id, tenant_id=tenant_id)
        permissions = _list_permissions(connection, user_id=user_id)
        connection.commit()

    return LoginResponse(
        token=token,
        expires_at=expires_at.isoformat(),
        refresh_token=refresh_token,
        refresh_expires_at=refresh_expires_at.isoformat(),
        tenant_id=tenant_id,
        user_id=user_id,
        email=body.email,
        permissions=permissions,
    )


@router.post("/refresh", response_model=LoginResponse)
def refresh(body: RefreshRequest) -> LoginResponse:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT rt.user_id, rt.tenant_id, rt.expires_at, rt.revoked_at, u.email
            FROM core.refresh_tokens rt
            JOIN core.users u ON u.id = rt.user_id
            WHERE rt.token = %s
            """,
            (body.refresh_token,),
        ).fetchone()

        if row is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")

        user_id, tenant_id, expires_at, revoked_at, email = row

        if revoked_at is not None:
            # This refresh token was already rotated away once. Someone
            # presenting it again means either the legitimate client retried
            # a stale copy, or it was stolen after rotation — either way,
            # the safe response is to kill every active credential this
            # user has and force a real re-login.
            connection.execute("DELETE FROM core.sessions WHERE user_id = %s", (user_id,))
            connection.execute(
                "UPDATE core.refresh_tokens SET revoked_at = NOW() WHERE user_id = %s AND revoked_at IS NULL",
                (user_id,),
            )
            connection.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token already used")

        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token expired")

        connection.execute(
            "UPDATE core.refresh_tokens SET revoked_at = NOW() WHERE token = %s",
            (body.refresh_token,),
        )
        token, new_expires_at = _issue_session(connection, user_id=user_id, tenant_id=tenant_id)
        new_refresh_token, new_refresh_expires_at = _issue_refresh_token(
            connection, user_id=user_id, tenant_id=tenant_id
        )
        permissions = _list_permissions(connection, user_id=user_id)
        connection.commit()

    return LoginResponse(
        token=token,
        expires_at=new_expires_at.isoformat(),
        refresh_token=new_refresh_token,
        refresh_expires_at=new_refresh_expires_at.isoformat(),
        tenant_id=tenant_id,
        user_id=user_id,
        email=email,
        permissions=permissions,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout(body: LogoutRequest, tenant: TenantContext = Depends(require_session)) -> None:
    """Revokes the session (and refresh token, if given) server-side; a stolen
    token stops working immediately instead of at natural expiry."""
    with get_connection() as connection:
        connection.execute("DELETE FROM core.sessions WHERE token = %s", (tenant.session_token,))
        if body.refresh_token is not None:
            connection.execute(
                "UPDATE core.refresh_tokens SET revoked_at = NOW() WHERE token = %s",
                (body.refresh_token,),
            )
        connection.commit()
