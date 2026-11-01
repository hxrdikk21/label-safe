"""
FastAPI middleware for request correlation, latency profiling, and error handling.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.rxguard.auth.jwt import AuthError
from src.rxguard.core.logging import REQUEST_ID
from src.rxguard.users.context_guard import AccessDeniedError

logger = logging.getLogger(__name__)


# The SPA loads only its own scripts; React style attributes need 'unsafe-inline' for styles,
# and the Archivo font comes from Google Fonts.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-Frame-Options": "DENY",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Browser hardening on every response: bearer tokens live in localStorage, so the CSP is what
    stops injected scripts from reading them. HSTS is added by the TLS proxy (deployment/Caddyfile)."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Injects unique X-Request-ID and tracks request latency X-Process-Time-Ms."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or f"REQ-{uuid.uuid4().hex[:12].upper()}"
        request.state.request_id = request_id
        REQUEST_ID.set(request_id)  # every log line of this request carries it
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except AuthError as e:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "UNAUTHORIZED",
                    "detail": str(e),
                    "request_id": request_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except AccessDeniedError as e:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "ACCESS_DENIED",
                    "detail": str(e),
                    "request_id": request_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception:
            logger.exception("Unhandled error (request_id=%s)", request_id)
            return JSONResponse(
                status_code=500,
                content={
                    "error": "INTERNAL_SERVER_ERROR",
                    "detail": "An internal error occurred during clinical safety processing",
                    "request_id": request_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        process_time_ms = int((time.perf_counter() - start_time) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(process_time_ms)
        return response
