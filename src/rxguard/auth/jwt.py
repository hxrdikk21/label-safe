"""
JSON Web Token (JWT) management services.
Issues and cryptographically validates access and refresh tokens.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pydantic import BaseModel, Field

from src.rxguard.core.config import get_settings


class TokenPayload(BaseModel):
    """Decoded JWT payload claims."""

    sub: str = Field(..., description="User ID subject")
    roles: list[str] = Field(default_factory=lambda: ["ROLE_USER"])
    type: str = Field(default="access", description="'access' or 'refresh'")
    exp: int = Field(..., description="Expiration timestamp")
    iat: int = Field(..., description="Issued at timestamp")
    jti: str | None = Field(default=None, description="Token id (refresh tokens; used for rotation)")


class AuthError(Exception):
    """Authentication or token verification error."""

    pass


def create_access_token(
    user_id: str,
    roles: list[str] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Generates a signed JWT access token."""
    settings = get_settings()
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "roles": roles or ["ROLE_USER"],
        "type": "access",
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    user_id: str,
    expires_delta: timedelta | None = None,
    jti: str | None = None,
) -> str:
    """Generates a signed JWT refresh token carrying a unique ``jti`` for rotation/revocation."""
    settings = get_settings()
    now = datetime.now(UTC)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.refresh_token_expire_days)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "jti": jti or uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> TokenPayload:
    """
    Decodes and cryptographically validates a JWT token.
    Raises AuthError if token is invalid, expired, or tampered.
    """
    settings = get_settings()
    try:
        data = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
        return TokenPayload(**data)
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Token has expired") from e
    except (jwt.InvalidTokenError, jwt.DecodeError) as e:
        raise AuthError(f"Invalid token: {e!s}") from e
