"""Production hardening: browser security headers, no public API docs, no wildcard CORS."""

import os
import subprocess
import sys

from starlette.testclient import TestClient

from src.labelsafe.api.main import app

STRONG_SECRET = "x" * 48


def run_app(**env: str) -> subprocess.CompletedProcess[str]:
    """Imports the app in a fresh interpreter with ``env`` and asks for /docs."""
    code = (
        "from starlette.testclient import TestClient; from src.labelsafe.api.main import app; "
        "print(TestClient(app).get('/docs').status_code)"
    )
    return subprocess.run(  # noqa: S603 - fixed interpreter and code, test-only
        [sys.executable, "-c", code],
        env={**os.environ, "MODEL_MODE": "fake", "JWT_SECRET_KEY": STRONG_SECRET, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_every_response_carries_security_headers() -> None:
    res = TestClient(app).get("/api/v1/health")
    csp = res.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"


def test_api_docs_are_hidden_in_production() -> None:
    assert run_app(APP_ENV="development").stdout.strip() == "200"
    assert run_app(APP_ENV="production").stdout.strip() == "404"


def test_production_refuses_wildcard_cors() -> None:
    proc = run_app(APP_ENV="production", CORS_ORIGINS='["*"]')
    assert proc.returncode != 0 and "CORS_ORIGINS" in proc.stderr


def test_cross_origin_requests_are_not_allowed_by_default() -> None:
    res = TestClient(app).options(
        "/api/v1/health", headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "GET"}
    )
    assert res.headers.get("access-control-allow-origin") is None
