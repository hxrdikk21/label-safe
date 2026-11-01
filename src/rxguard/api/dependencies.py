"""
FastAPI dependency injection providers.
Supplies singleton engines and security dependencies for route handlers.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.rxguard.auth.jwt import AuthError, TokenPayload, decode_token
from src.rxguard.auth.rate_limit import (
    Counters,
    LoginRateLimiter,
    MemoryCounters,
    RequestLimiter,
    SqlCounters,
)
from src.rxguard.auth.store import AuthStore, InMemoryAuthStore, SqlAuthStore
from src.rxguard.core.config import Settings, get_settings
from src.rxguard.database.connection import create_engine, create_session_factory
from src.rxguard.rag.generator import GeminiChat
from src.rxguard.rag.generator import get_chat_model as get_chat_model_for
from src.rxguard.rag.retriever import InMemoryRetriever, PostgresRetriever, Retriever
from src.rxguard.rag.service import RagService
from src.rxguard.safety.engine import SafetyEngine
from src.rxguard.users.profile_store import InMemoryProfileStore, ProfileStore, SqlProfileStore
from src.rxguard.users.service import UserService

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """One pooled engine for the process, enabled only when DATABASE_URL is set (environment or .env)."""
    settings = Settings()  # fresh, not the cached get_settings(), so tests can toggle the environment
    # The built-in default URL doesn't count: without an explicit setting the app runs in memory.
    if "database_url" not in settings.model_fields_set or not settings.database_url:
        return None
    return create_session_factory(create_engine(settings.database_url))


@lru_cache
def get_auth_store() -> AuthStore:
    """Users and credentials in PostgreSQL when configured; in-memory otherwise (tests, offline)."""
    factory = get_session_factory()
    return SqlAuthStore(factory) if factory is not None else InMemoryAuthStore()


@lru_cache
def get_profile_store() -> ProfileStore:
    """Clinical profiles in PostgreSQL when configured; otherwise the in-process UserService."""
    factory = get_session_factory()
    return SqlProfileStore(factory) if factory is not None else InMemoryProfileStore(get_user_service())


@lru_cache
def get_counters() -> Counters:
    """Rate-limit counters in PostgreSQL when configured (shared by workers, kept across restarts)."""
    factory = get_session_factory()
    return SqlCounters(factory) if factory is not None else MemoryCounters()


@lru_cache
def get_login_rate_limiter() -> LoginRateLimiter:
    return LoginRateLimiter(max_failures=5, window_seconds=900, counters=get_counters())


@lru_cache
def get_request_limiter() -> RequestLimiter:
    return RequestLimiter(get_counters())


def per_ip_limit(name: str, setting: str, window_s: int = 60) -> Any:
    """Route dependency: at most ``Settings.<setting>`` requests per client IP per window, else 429.
    Behind the TLS proxy the client IP comes from X-Forwarded-For (uvicorn --proxy-headers)."""

    async def check(request: Request, limiter: RequestLimiter = Depends(get_request_limiter)) -> None:
        client = request.client.host if request.client else "unknown"
        retry = await limiter.hit(f"{name}|{client}", getattr(get_settings(), setting), window_s)
        if retry:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Try again in {retry} s.",
                headers={"Retry-After": str(retry)},
            )

    return Depends(check)


@lru_cache
def get_safety_engine() -> SafetyEngine:
    """Returns singleton SafetyEngine instance."""
    return SafetyEngine()


@lru_cache
def get_retriever() -> Retriever:
    """Postgres hybrid retrieval when DATABASE_URL is set; otherwise an empty corpus (always abstains)."""
    factory = get_session_factory()
    return PostgresRetriever(factory) if factory is not None else InMemoryRetriever()


@lru_cache
def get_rag_service() -> RagService:
    return RagService(get_retriever())


@lru_cache
def _gemini() -> GeminiChat | None:
    return get_chat_model_for()


async def get_chat_model(limiter: RequestLimiter = Depends(get_request_limiter)) -> GeminiChat | None:
    """Gemini when configured and today's call budget (GEMINI_DAILY_BUDGET) isn't spent; None means
    offline replies that quote the labels. Each chat or explanation request counts as one call."""
    chat = _gemini()
    if chat is None:
        return None
    if await limiter.hit("gemini|daily", get_settings().gemini_daily_budget, 86_400):
        return None
    return chat


@lru_cache
def get_user_service() -> UserService:
    """Returns singleton UserService instance."""
    return UserService()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> TokenPayload:
    """Validates incoming Authorization: Bearer <JWT> token and returns TokenPayload."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
        if payload.type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type: access token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except AuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenPayload | None:
    """Optional bearer auth: returns TokenPayload if valid token supplied, None otherwise."""
    if not credentials or not credentials.credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        return payload if payload.type == "access" else None
    except Exception:
        return None


def require_role(required_role: str) -> Callable[[TokenPayload], TokenPayload]:
    """Enforces role-based access control (RBAC)."""

    def role_checker(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if required_role not in user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: User lacks required role '{required_role}'",
            )
        return user

    return role_checker


def require_any_role(*required_roles: str) -> Callable[[TokenPayload], TokenPayload]:
    """Enforces that authenticated user holds at least one of the specified roles."""

    def role_checker(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if not any(r in user.roles for r in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: User lacks one of required roles: {list(required_roles)}",
            )
        return user

    return role_checker
