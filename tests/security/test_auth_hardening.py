"""
Auth hardening and profile persistence through the API (in-memory stores):
privilege escalation at registration, refresh rotation with reuse detection,
login rate limiting, one-time backup codes, logout, and the profile endpoints.
"""

from collections.abc import Iterator
from typing import Any

import pyotp
import pytest
from starlette.testclient import TestClient

from src.labelsafe.api import dependencies
from src.labelsafe.api.main import app
from src.labelsafe.auth.rate_limit import LoginRateLimiter
from src.labelsafe.auth.store import InMemoryAuthStore
from src.labelsafe.users.profile_store import InMemoryProfileStore
from src.labelsafe.users.service import UserService

PASSWORD = "CorrectHorseBattery9!"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Fresh stores and limiter per test so state never leaks between tests."""
    store, limiter = InMemoryAuthStore(), LoginRateLimiter(max_failures=3, window_seconds=60)
    profiles = InMemoryProfileStore(UserService())
    app.dependency_overrides[dependencies.get_auth_store] = lambda: store
    app.dependency_overrides[dependencies.get_login_rate_limiter] = lambda: limiter
    app.dependency_overrides[dependencies.get_profile_store] = lambda: profiles
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def register_and_login(client: TestClient, username: str = "alice") -> dict[str, Any]:
    assert (
        client.post("/api/v1/auth/register", json={"username": username, "password": PASSWORD}).status_code
        == 201
    )
    res = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_registration_honeypot_rejects_bots(client: TestClient) -> None:
    bot = {"username": "spambot", "password": PASSWORD, "website": "http://spam.example"}
    assert client.post("/api/v1/auth/register", json=bot).status_code == 422
    human = {"username": "human", "password": PASSWORD, "website": None}
    assert client.post("/api/v1/auth/register", json=human).status_code == 201


def test_self_registration_cannot_grant_admin(client: TestClient) -> None:
    res = client.post(
        "/api/v1/auth/register", json={"username": "mallory", "password": PASSWORD, "roles": ["ROLE_ADMIN"]}
    )
    assert res.status_code == 403
    tokens = register_and_login(client, "bob")
    profile = client.get("/api/v1/users/me/profile", headers=bearer(tokens["access_token"])).json()
    assert profile["roles"] == ["ROLE_USER"]
    assert (
        client.post("/api/v1/auth/register", json={"username": "bob", "password": PASSWORD}).status_code
        == 409
    )


def test_refresh_rotates_and_detects_reuse(client: TestClient) -> None:
    first = register_and_login(client)
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    rotated = second.json()
    assert rotated["refresh_token"] != first["refresh_token"] and rotated["access_token"]

    # Replaying the old token is reuse: rejected, and the newer session is revoked too.
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401 and "reuse" in replay.json()["detail"]
    after = client.post("/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert after.status_code == 401


def test_refresh_rejects_access_tokens_and_garbage(client: TestClient) -> None:
    tokens = register_and_login(client)
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
    )
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-jwt"}).status_code == 401


def test_logout_revokes_refresh_tokens(client: TestClient) -> None:
    tokens = register_and_login(client)
    assert client.post("/api/v1/auth/logout", headers=bearer(tokens["access_token"])).status_code == 204
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code
        == 401
    )


def test_login_is_rate_limited_and_success_resets(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json={"username": "carol", "password": PASSWORD})
    for _ in range(2):
        assert (
            client.post("/api/v1/auth/login", json={"username": "carol", "password": "wrong"}).status_code
            == 401
        )
    assert (
        client.post("/api/v1/auth/login", json={"username": "carol", "password": PASSWORD}).status_code == 200
    )
    for _ in range(3):
        client.post("/api/v1/auth/login", json={"username": "carol", "password": "wrong"})
    locked = client.post("/api/v1/auth/login", json={"username": "carol", "password": PASSWORD})
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    # Unknown usernames are counted too, without revealing whether the account exists.
    for _ in range(3):
        assert (
            client.post("/api/v1/auth/login", json={"username": "ghost", "password": "x"}).status_code == 401
        )
    assert client.post("/api/v1/auth/login", json={"username": "ghost", "password": "x"}).status_code == 429


def test_totp_and_one_time_backup_codes(client: TestClient) -> None:
    tokens = register_and_login(client, "dave")
    setup = client.post("/api/v1/auth/2fa/setup", headers=bearer(tokens["access_token"])).json()
    code = pyotp.TOTP(setup["secret"]).now()
    assert (
        client.post(
            "/api/v1/auth/2fa/verify", json={"code": code}, headers=bearer(tokens["access_token"])
        ).status_code
        == 200
    )

    pending = client.post("/api/v1/auth/login", json={"username": "dave", "password": PASSWORD}).json()
    assert pending["requires_2fa"] is True and pending["access_token"] == ""
    with_totp = client.post(
        "/api/v1/auth/login",
        json={"username": "dave", "password": PASSWORD, "totp_code": pyotp.TOTP(setup["secret"]).now()},
    )
    assert with_totp.status_code == 200 and with_totp.json()["access_token"]

    backup = setup["backup_codes"][0]
    first_use = client.post(
        "/api/v1/auth/login", json={"username": "dave", "password": PASSWORD, "backup_code": backup}
    )
    assert first_use.status_code == 200
    second_use = client.post(
        "/api/v1/auth/login", json={"username": "dave", "password": PASSWORD, "backup_code": backup}
    )
    assert second_use.status_code == 401  # one-time


def test_profile_crud_feeds_saved_profile_analysis(client: TestClient) -> None:
    tokens = register_and_login(client, "erin")
    headers = bearer(tokens["access_token"])
    put = client.put(
        "/api/v1/users/me/profile",
        headers=headers,
        json={
            "active_medications": ["Warfarin", " ", "Warfarin"],
            "allergies": [{"substance_name": "Penicillin", "severity": "SEVERE_ANAPHYLAXIS"}],
            "conditions": [{"condition_name": "Peptic Ulcer", "icd10_code": "K27"}],
        },
    )
    assert put.status_code == 200, put.text
    profile = client.get("/api/v1/users/me/profile", headers=headers).json()
    assert profile["user_id"] == "erin" and profile["active_medications"] == ["Warfarin"]
    assert profile["conditions"][0]["icd10_code"] == "K27"

    ibuprofen = {"rxcui": "5640", "canonical_name": "Ibuprofen", "term_type": "IN"}
    report = client.post(
        "/api/v1/safety/analyze",
        headers=headers,
        json={"medications": [ibuprofen], "use_saved_profile": True},
    ).json()
    assert not any("not supplied" in w for w in report["missing_data_warnings"])  # saved profile was used

    assert client.delete("/api/v1/users/me/profile", headers=headers).status_code == 204
    assert client.get("/api/v1/users/me/profile", headers=headers).json()["active_medications"] == []
    assert client.get("/api/v1/users/me/profile").status_code == 401


async def test_rate_limiter_window_expiry() -> None:
    now = [0.0]
    limiter = LoginRateLimiter(max_failures=2, window_seconds=10, clock=lambda: now[0])
    await limiter.record_failure("k")
    await limiter.record_failure("k")
    assert await limiter.retry_after("k") == 10  # locked until the 10 s window ends
    now[0] = 10.5
    assert await limiter.retry_after("k") == 0
    await limiter.record_failure("k")
    await limiter.reset("k")
    assert await limiter.retry_after("k") == 0


def test_password_policy_enforcement(client: TestClient) -> None:
    # 1. Too short (< 8 chars)
    res = client.post("/api/v1/auth/register", json={"username": "user1", "password": "Sh1!"})
    assert res.status_code == 422

    # 2. No uppercase
    res = client.post("/api/v1/auth/register", json={"username": "user2", "password": "nouppercase123!"})
    assert res.status_code == 422

    # 3. No lowercase
    res = client.post("/api/v1/auth/register", json={"username": "user3", "password": "NOLOWERCASE123!"})
    assert res.status_code == 422

    # 4. No digit
    res = client.post("/api/v1/auth/register", json={"username": "user4", "password": "NoDigitHere!@#"})
    assert res.status_code == 422

    # 5. No special char
    res = client.post("/api/v1/auth/register", json={"username": "user5", "password": "NoSpecialChar123"})
    assert res.status_code == 422


def test_auth_me_never_leaks_totp_secret(client: TestClient) -> None:
    tokens = register_and_login(client, "secret_check_user")
    headers = bearer(tokens["access_token"])
    setup = client.post("/api/v1/auth/2fa/setup", headers=headers).json()
    assert "secret" in setup

    me_info = client.get("/api/v1/auth/me", headers=headers).json()
    assert "totp_secret" not in me_info
    assert "secret" not in me_info
    assert me_info["totp_enabled"] is False

    # Complete 2FA verification
    code = pyotp.TOTP(setup["secret"]).now()
    verify_res = client.post("/api/v1/auth/2fa/verify", headers=headers, json={"code": code})
    assert verify_res.status_code == 200

    # After verification, /auth/me still never contains totp_secret
    me_info_after = client.get("/api/v1/auth/me", headers=headers).json()
    assert "totp_secret" not in me_info_after
    assert "secret" not in me_info_after
    assert me_info_after["totp_enabled"] is True
