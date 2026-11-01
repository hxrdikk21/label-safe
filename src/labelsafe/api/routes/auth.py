"""
Authentication and 2FA API routes.
Implements /register, /login, /refresh, /logout, /2fa/setup, and /2fa/verify.

Credentials live in the AuthStore (PostgreSQL when DATABASE_URL is set). Login is
rate limited per username and client address, refresh tokens are single-use
(rotation, with reuse detection revoking the user's other sessions), and 2FA
backup codes are one-time and stored only as hashes.
"""

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from src.labelsafe.api.dependencies import (
    client_ip,
    get_auth_store,
    get_current_user,
    get_login_rate_limiter,
    per_ip_limit,
)
from src.labelsafe.auth.hasher import hash_password, verify_password
from src.labelsafe.auth.jwt import (
    AuthError,
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from src.labelsafe.auth.rate_limit import LoginRateLimiter
from src.labelsafe.auth.store import AuthStore, AuthUser, UserExistsError
from src.labelsafe.auth.two_factor import (
    generate_backup_codes,
    generate_totp_secret,
    get_totp_uri,
    verify_totp_code,
)
from src.labelsafe.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["Authentication & 2FA"])

# Self-registration always yields ROLE_USER; asking for an operator-only role is rejected outright.
PRIVILEGED_ROLES = frozenset({"ROLE_ADMIN"})


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    email: str | None = Field(default=None)
    full_name: str | None = Field(default=None, max_length=128)
    role: str = Field(default="ROLE_USER", description="Ignored except ROLE_ADMIN, which is rejected")
    roles: list[str] = Field(
        default_factory=list, description="Optional extra roles; rejected if contains ROLE_ADMIN"
    )
    # Honeypot: the sign-up form hides this field from people, so any value means a bot (422).
    website: str | None = Field(default=None, max_length=0)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not any(c.isupper() for c in value):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in value):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in value):
            raise ValueError("Password must contain at least one numerical digit")
        if not any(not c.isalnum() for c in value):
            raise ValueError("Password must contain at least one special character")
        return value


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = None
    backup_code: str | None = Field(default=None, description="One-time recovery code instead of TOTP")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"  # noqa: S105 - OAuth token type, not a credential
    requires_2fa: bool = False
    roles: list[str] = Field(default_factory=lambda: ["ROLE_USER"])
    username: str = ""
    user_id: str = ""


class RefreshRequest(BaseModel):
    refresh_token: str


class TOTPSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    backup_codes: list[str]


class TOTPVerifyRequest(BaseModel):
    code: str


class TOTPSetupRequest(BaseModel):
    code: str | None = Field(default=None, description="Current authenticator code; required to re-enrol")


@lru_cache
def _dummy_hash() -> str:
    """Compared against for unknown usernames so timing does not reveal which accounts exist."""
    return hash_password("labelsafe-timing-equalizer")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def _issue_tokens(store: AuthStore, user: AuthUser) -> TokenResponse:
    settings = get_settings()
    jti = uuid.uuid4().hex
    refresh_token = create_refresh_token(user_id=user.user_id, jti=jti)
    await store.store_refresh_token(
        jti, user.user_id, datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    )
    return TokenResponse(
        access_token=create_access_token(user_id=user.user_id, roles=user.roles),
        refresh_token=refresh_token,
        requires_2fa=False,
        roles=user.roles,
        username=user.username,
        user_id=user.user_id,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=[per_ip_limit("register", "rate_limit_register_per_hour", 3600)],
)
async def register(
    request: RegisterRequest,
    store: AuthStore = Depends(get_auth_store),
) -> dict[str, object]:
    """Registers a new user with Argon2id password hashing."""
    requested_roles = set(request.roles)
    if request.role:
        requested_roles.add(request.role)

    if PRIVILEGED_ROLES.intersection(requested_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Privileged roles (ROLE_ADMIN) cannot be self-assigned without authorization",
        )

    try:
        password_hash = await run_in_threadpool(hash_password, request.password)
        user = await store.create(request.username, request.email, password_hash, full_name=request.full_name)
    except UserExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{request.username}' already exists",
        ) from exc

    return {
        "message": "User registered successfully",
        "username": user.username,
        "user_id": user.user_id,
        "role": "ROLE_USER",
        "full_name": user.full_name,
    }


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    store: AuthStore = Depends(get_auth_store),
    limiter: LoginRateLimiter = Depends(get_login_rate_limiter),
) -> TokenResponse:
    """Authenticates user and returns JWT tokens; enforces TOTP 2FA (or a backup code) if enabled."""
    key = f"{request.username.lower()}|{client_ip(http_request)}"
    retry_after = await limiter.retry_after(key)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )

    user = await store.get_by_username(request.username)
    password_ok = await run_in_threadpool(
        verify_password, request.password, user.password_hash if user else _dummy_hash()
    )
    if user is None or not password_ok:
        await limiter.record_failure(key)
        raise _unauthorized("Invalid username or password")

    # If TOTP 2FA is enabled on this account
    if user.totp_enabled:
        if not request.totp_code and not request.backup_code:
            return TokenResponse(
                access_token="",
                refresh_token="",
                requires_2fa=True,
                username=user.username,
                user_id=user.user_id,
            )
        totp_ok = bool(
            request.totp_code and user.totp_secret and verify_totp_code(user.totp_secret, request.totp_code)
        )
        backup_ok = bool(
            request.backup_code and await store.consume_backup_code(user.user_id, request.backup_code)
        )
        if not (totp_ok or backup_ok):
            await limiter.record_failure(key)
            raise _unauthorized("Invalid 2FA authentication code")

    await limiter.reset(key)
    return await _issue_tokens(store, user)


@router.get("/me")
async def get_current_user_info(
    current_user: TokenPayload = Depends(get_current_user),
    store: AuthStore = Depends(get_auth_store),
) -> dict[str, object]:
    """Returns profile and role metadata for authenticated caller."""
    user = await store.get_by_id(current_user.sub)
    username = user.username if user else current_user.sub
    email = user.email if user else None
    totp_enabled = user.totp_enabled if user else False
    full_name = user.full_name if user else None
    return {
        "user_id": current_user.sub,
        "username": username,
        "email": email,
        "full_name": full_name,
        "roles": current_user.roles,
        "totp_enabled": totp_enabled,
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest, store: AuthStore = Depends(get_auth_store)) -> TokenResponse:
    """Exchanges a refresh token for a new token pair. Each refresh token works once."""
    try:
        payload = decode_token(request.refresh_token)
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc
    if payload.type != "refresh" or not payload.jti:
        raise _unauthorized("A refresh token is required")

    outcome = await store.rotate_refresh_token(payload.jti, payload.sub)
    if outcome == "reused":
        await store.revoke_all_refresh_tokens(payload.sub)
        raise _unauthorized("Refresh token reuse detected; all sessions revoked")
    if outcome != "rotated":
        raise _unauthorized("Refresh token is not valid")

    user = await store.get_by_id(payload.sub)
    if user is None:
        raise _unauthorized("Account no longer exists")
    return await _issue_tokens(store, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: TokenPayload = Depends(get_current_user),
    store: AuthStore = Depends(get_auth_store),
) -> None:
    """Revokes all of the caller's refresh tokens (access tokens expire on their own)."""
    await store.revoke_all_refresh_tokens(current_user.sub)


@router.post("/2fa/setup", response_model=TOTPSetupResponse)
async def setup_2fa(
    request: TOTPSetupRequest | None = None,
    current_user: TokenPayload = Depends(get_current_user),
    store: AuthStore = Depends(get_auth_store),
) -> TOTPSetupResponse:
    """Initializes TOTP 2FA secret and one-time backup codes."""
    user = await store.get_by_id(current_user.sub)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # Replacing an active secret needs the current one, so a stolen access token can't take over 2FA.
    code = request.code if request else None
    if user.totp_enabled and not (code and user.totp_secret and verify_totp_code(user.totp_secret, code)):
        raise _unauthorized("Enter a current authenticator code to set up 2FA again")

    secret = generate_totp_secret()
    backup_codes = generate_backup_codes()
    await store.begin_totp_setup(user.user_id, secret, [hash_password(c) for c in backup_codes])
    return TOTPSetupResponse(
        secret=secret,
        otpauth_uri=get_totp_uri(secret=secret, account_name=user.username),
        backup_codes=backup_codes,
    )


@router.post("/2fa/verify")
async def verify_2fa(
    request: TOTPVerifyRequest,
    current_user: TokenPayload = Depends(get_current_user),
    store: AuthStore = Depends(get_auth_store),
) -> dict[str, str]:
    """Verifies TOTP token to activate 2FA."""
    user = await store.get_by_id(current_user.sub)
    if not user or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA setup has not been initiated for this account",
        )
    if not verify_totp_code(user.totp_secret, request.code):
        raise _unauthorized("Invalid verification code")
    await store.enable_totp(user.user_id)
    return {"message": "Two-factor authentication successfully enabled"}
