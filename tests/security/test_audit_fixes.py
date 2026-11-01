"""Security regressions from the 2026-10-28 audit: roles, 2FA, CORS, limits."""

import os
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pyotp
import pytest
from starlette.testclient import TestClient

from src.labelsafe.api import dependencies
from src.labelsafe.api.main import app
from src.labelsafe.auth.rate_limit import LoginRateLimiter
from src.labelsafe.auth.store import InMemoryAuthStore

PASSWORD = "CorrectHorseBattery9!"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    store = InMemoryAuthStore()
    app.dependency_overrides[dependencies.get_auth_store] = lambda: store
    app.dependency_overrides[dependencies.get_login_rate_limiter] = lambda: LoginRateLimiter(10, 60)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def register(client: TestClient, username: str, **extra: Any) -> dict[str, Any]:
    res = client.post("/api/v1/auth/register", json={"username": username, "password": PASSWORD, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def login(client: TestClient, username: str) -> dict[str, Any]:
    return client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD}).json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_self_registration_always_gets_role_user(client: TestClient) -> None:
    assert register(client, "dana", role="ROLE_CLINICIAN")["role"] == "ROLE_USER"
    tokens = login(client, "dana")
    me = client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"])).json()
    assert me["roles"] == ["ROLE_USER"]


def test_reenrolling_2fa_needs_the_current_code(client: TestClient) -> None:
    register(client, "erin")
    token = login(client, "erin")["access_token"]
    secret = client.post("/api/v1/auth/2fa/setup", headers=bearer(token)).json()["secret"]
    code = pyotp.TOTP(secret).now()
    assert (
        client.post("/api/v1/auth/2fa/verify", json={"code": code}, headers=bearer(token)).status_code == 200
    )

    assert client.post("/api/v1/auth/2fa/setup", headers=bearer(token)).status_code == 401
    again = client.post(
        "/api/v1/auth/2fa/setup", json={"code": pyotp.TOTP(secret).now()}, headers=bearer(token)
    )
    assert again.status_code == 200


def test_cors_never_allows_credentials(client: TestClient) -> None:
    res = client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "GET"},
    )
    assert res.headers.get("access-control-allow-credentials") is None


def test_request_lists_are_bounded(client: TestClient) -> None:
    meds = [{"rxcui": str(i), "canonical_name": f"drug{i}", "term_type": "IN"} for i in range(51)]
    assert client.post("/api/v1/safety/analyze", json={"medications": meds}).status_code == 422


@pytest.mark.parametrize("secret", ["", "too-short"])
def test_app_refuses_weak_jwt_secret(secret: str) -> None:
    env = {**os.environ, "JWT_SECRET_KEY": secret, "MODEL_MODE": "fake"}
    proc = subprocess.run(
        [sys.executable, "-c", "import src.labelsafe.api.main"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "JWT_SECRET_KEY" in proc.stderr
