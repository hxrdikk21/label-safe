"""
Main FastAPI application gateway for RxGuard-RAG platform.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.rxguard.api.middleware import RequestTracingMiddleware, SecurityHeadersMiddleware
from src.rxguard.api.routes import (
    auth,
    chat,
    evidence,
    health,
    medications,
    safety,
    stats,
    users,
    vocab,
)
from src.rxguard.core.config import get_settings
from src.rxguard.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

# An empty or short HMAC key makes tokens forgeable; the built-in default is only for local development.
_DEFAULT_JWT_SECRET = type(settings).model_fields["jwt_secret_key"].default
if len(settings.jwt_secret_key) < 32 or (
    settings.app_env == "production" and settings.jwt_secret_key == _DEFAULT_JWT_SECRET
):
    raise RuntimeError("Set JWT_SECRET_KEY to a random value of at least 32 characters")
PRODUCTION = settings.app_env == "production"
if PRODUCTION and "*" in settings.cors_origins:
    raise RuntimeError("CORS_ORIGINS must list real origins in production, not '*'")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    warm = asyncio.create_task(health.warm_up())
    yield
    warm.cancel()


app = FastAPI(
    lifespan=lifespan,
    title="RxGuard-RAG Clinical Safety Intelligence Platform",
    description=(
        "Evidence-grounded medication safety intelligence platform featuring deterministic clinical "
        "screening, citation-verified grounded explanations, and evidence provenance."
    ),
    version="0.1.0",
    # The API schema and docs are for development; production doesn't advertise its surface.
    docs_url=None if PRODUCTION else "/docs",
    redoc_url=None if PRODUCTION else "/redoc",
    openapi_url=None if PRODUCTION else "/openapi.json",
)

# 1. Tracing & Profiling Middleware, then browser security headers on every response
app.add_middleware(RequestTracingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# 2. CORS Middleware (auth uses bearer headers, not cookies, so credentials are never needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Mount API Routers under /api/v1
API_PREFIX = "/api/v1"

app.include_router(health.router, prefix=API_PREFIX)
app.include_router(safety.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(evidence.router, prefix=API_PREFIX)
app.include_router(chat.router, prefix=API_PREFIX)
app.include_router(medications.router, prefix=API_PREFIX)
app.include_router(vocab.router, prefix=API_PREFIX)
app.include_router(stats.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)

# Also expose top-level health probe
app.include_router(health.router)


if settings.frontend_dist:
    # Production: the built SPA at / (hash routing, so no server-side fallback is needed).
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
else:

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "platform": "RxGuard-RAG",
            "tagline": "Evidence-grounded medication safety intelligence",
            "status": "OPERATIONAL",
            "docs": "/docs",
            "disclaimer": settings.clinical_disclaimer,
        }
